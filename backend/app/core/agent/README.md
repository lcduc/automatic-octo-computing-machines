# `backend/app/core/agent/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
The chat engine for one turn: decide how a message is answered (canned reply, tool call or
knowledge base), call the LLM provider, and stream `TurnEvent`s back. It also owns the LLM provider
clients, every prompt and canned reply, and the tool-calling mechanics (`tools/`).
It knows nothing about HTTP or the database rows of a conversation: `services/chat_service.py`
persists what it yields. Message screening lives in [`../guardrails/`](../guardrails/), meaning-based
routing in [`../routing/`](../routing/), search in [`../retrieval/`](../retrieval/).

**Project rule:** every prompt and every auto reply lives in [`prompts.py`](prompts.py)
(`SystemPrompts`, `AutoReplies`). Never put prompt text in env vars, settings or inline strings in
another module.

## Files

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package docstring only. |
| `chatbot.py` | `ChatbotService`, `PURPOSE_INTENT`, `PURPOSE_TOOL` | Routes one turn (staff takeover, guard, sensitive topic, embedding router, intent router) and maps timeouts/errors to a safe `TurnResult`. |
| `knowledge_answerer.py` | `KnowledgeAnswerer`, `GenerationGate`, `PURPOSE_ANSWER`, `PURPOSE_REWRITE` | Knowledge path: rewrite, retrieve, fallback, answer cache, grounded streamed answer, citations, confidence. |
| `turn_deadline.py` | `TurnDeadline` | One time budget per turn: `after()`, `remaining()`, `guard(stream)`; raises `asyncio.TimeoutError`. |
| `tool_calling_agent.py` | `ToolCallingAgent`, `MAX_TOOL_CALLS_PER_TURN` | One tool-calling round over OpenAI: rewrite, decision call with tool schemas (`decide()`, also scored by `scripts/eval/tool_selection.py`), run tools, stream the final answer. |
| `intent_router.py` | `IntentRouter` | LLM classifier: `rag`, `action` or `login`; skips the call when no tool is offered; defaults to RAG on failure. |
| `query_rewriter.py` | `QueryRewriter` | Light-model rewrite of a follow-up into a standalone query; also restores missing Vietnamese accents. |
| `answer_marker.py` | `NoAnswerFilter` | Holds back the stream start until it is known not to be `[NO_ANSWER]`; a marker turns the turn into a fallback. |
| `confidence.py` | `ConfidenceScore`, `ConfidenceScorer` | Heuristic answer confidence (context alignment, length, coherence, hedging words). |
| `history.py` | `recent_history`, `ALLOWED_HISTORY_ROLES`, `FAILED_TURN_OUTCOME` | Last N user/assistant messages; drops other roles and failed-turn apologies. |
| `prompts.py` | `SystemPrompts`, `AutoReplies`, `PromptManager` | All prompt text and canned replies (Vietnamese); builds the system prompt and the user turn. |
| `response_cache.py` | `ResponseCache` | In-process TTL + LRU cache of generated answers; key = query, documents block, history, namespace. |
| `base_llm_provider.py` | `BaseLLMProvider` | Provider contract: `complete`, `complete_async`, `stream`, `check_availability`, `close`; OpenAI message format. |
| `provider_factory.py` | `LLMProviderFactory` | Builds the provider named by `LLM_PROVIDER` (`openai`, `anthropic`, `gemini`, `stub`); unknown -> OpenAI. |
| `openai_client.py` | `OpenAIClientProvider`, `LEGACY_PARAMETER_MODEL_PREFIXES`, `LOCAL_SERVER_API_KEY` | OpenAI SDK owner; also moderation, transcription and tool calling (`complete_with_tools_async`); supports `OPENAI_BASE_URL`. |
| `anthropic_client.py` | `AnthropicClientProvider` | Anthropic SDK owner; moves the system prompt to the top-level `system` parameter. |
| `gemini_client.py` | `GeminiClientProvider`, `MILLISECONDS_PER_SECOND` | Google Gen AI SDK owner on the stateless `generate_content` surface. |
| `stub_client.py` | `StubClientProvider`, `STUB_WORDS`, `CHARS_PER_TOKEN`, `MILLISECONDS_PER_SECOND` | Deterministic fake provider for load tests (`LLM_PROVIDER=stub`); refused when `APP_ENV=production`. |

### `tools/`
Tool-calling mechanics. `tools/__init__.py` only re-exports `BaseTool`, `CurrentTimeTool`, `ToolRegistry`.

| File | Public names | What it does |
|---|---|---|
| `base.py` | `BaseTool` | Shape of a tool: `name`, `description`, `parameters`, `required_tier_level`, `execute`, `permits`, `to_openai_schema`. |
| `registry.py` | `ToolRegistry`, `ToolSource` | Holds static tools plus a runtime `ToolSource`; offers only tools the caller's tier permits and refuses them again at execution. |
| `current_time_tool.py` | `CurrentTimeTool` | Reference tool (current date/time, no side effects); the template for new tools. |
| `sql_tool.py` | `SqlTool`, `SqlToolSpec`, `SqlToolDefinitionError`, `USER_PARAMETER`, `MASK`, `MASK_VISIBLE_CHARS` | Admin-defined parameterized read-only query; binds `:user_id` from the verified caller, keeps allowed columns, masks sensitive ones, caps rows/chars. |
| `sql_tool_executor.py` | `SqlToolExecutor`, `SqlToolTimeoutError` | Runs a SQL tool in a `READ ONLY` transaction with `statement_timeout` and `app.user_id` set for row-level security. |
| `tool_arguments.py` | `ToolArguments`, `ToolArgumentsError`, `RESERVED_PARAMETERS`, `FORMAT_DATE`, `FORMAT_PERIOD`, `FORMAT_AMOUNT`, `MAX_STRING_LENGTH` | Validates LLM-supplied arguments against a JSON Schema subset; parses `vn-period` and `vn-amount` into SQL parameters. |

### Flow: one chat turn
```
ChatService (services/) -> ChatbotService.run(request)
  deadline = TurnDeadline.after(TURN_TIMEOUT_SECONDS)       # one budget for the whole turn
  _run:
    staff active?                    -> HANDOFF (STAFF_ACTIVE)
    InputGuard.classify_rules        -> BLOCK / GREETING / THANKS / HUMAN_REQUESTED
    matching_topic (handoff mode)    -> HANDOFF (sensitive topic)
    expand_chat_abbreviations -> EmbeddingRouter.classify (thread)
                                     -> greeting / thanks / handoff / off_topic / clarify replies
    moderation = create_task(InputGuard.is_flagged)          # overlaps the work below
    IntentRouter.classify (only when tool calling is wired)
       LOGIN_REQUIRED                -> canned login reply
       ACTION -> await moderation -> ToolCallingAgent.stream, wrapped in deadline.guard
    else KnowledgeAnswerer.answer(..., before_generation=await moderation)
       QueryRewriter -> ContextRetriever.search (semaphore + deadline.remaining)
       no match -> off-topic DENIED or configured fallback (deny / handoff), no LLM call
       ResponseCache hit -> cached answer
       before_generation()           -> BLOCKED if moderation flagged
       llm.stream wrapped in deadline.guard -> NoAnswerFilter -> TurnDelta...
       TurnResult(ANSWERED, citations, confidence)
  asyncio.TimeoutError -> ERROR (streamed text or TIMEOUT); other errors -> ERROR (BUSY on 429, else ERROR)
```
Every path yields `TurnDelta` / `TurnUsage` events and exactly one final `TurnResult`. The rule is
cheapest work first: canned replies never pay for moderation, rewrite or retrieval.

## Dependencies
- May import: `app.core.guardrails`, `app.core.routing`, `app.core.retrieval`,
  `app.core.document_processing` (`section_label` for citations), `app.core.storage.database`
  (SQL executor), `app.models.*`, `app.utils.*`, `app.config.*`. Never `app.api` or `app.services`
  (layering: api -> services -> core -> models/utils; config at the bottom; only main.py imports
  middleware; enforced by `test/unit/test_layering.py`). Runtime SQL tools reach the registry through
  the `ToolSource` protocol, implemented by `services/sql_tool_catalog.py`, so core does not import it.
- Used by: `app/api/container.py` (wires `ChatbotService`, providers, tools), `services/chat_service.py`,
  `services/settings_service.py`, `services/sql_tool_catalog.py`, `services/transcription_service.py`,
  `scripts/manage.py`, `scripts/eval/intent_router.py`, `scripts/eval/tool_selection.py`, `scripts/eval/generate_synthetic_queries.py`.
- External: LLM APIs via `openai`, `anthropic`, `google-genai`; SQLAlchemy for the business database
  (SQL tools). The tool agent, moderation and transcription always use OpenAI (or an
  OpenAI-compatible `OPENAI_BASE_URL`), whatever `LLM_PROVIDER` is. Tool calling is off unless
  `TOOL_CALLING_ENABLED=true` and an OpenAI client is available.

## Run / test
From `backend/` with `venv` active:
```
pytest test/unit/test_chat_pipeline.py test/unit/test_chat_turn_recovery.py test/unit/test_chatbot_action_routing.py \
       test/unit/test_no_answer_filter.py test/unit/test_query_rewriter.py test/unit/test_intent_router.py \
       test/unit/test_tool_calling_agent.py test/unit/test_current_time_tool.py test/unit/test_stub_llm_provider.py \
       test/unit/test_openai_base_url.py test/unit/test_openai_completion_kwargs.py test/unit/test_transcription.py
pytest -m red_team -v                       # prompt-injection suite (also a CI step)
pytest test/integration/test_sql_tools.py   # needs TEST_DATABASE_URL (pgvector/pgvector:pg17)
ruff check .                                # from the repo root
```
`test_red_team.py` also covers tools and prompts. Intent-router eval: `python -m scripts.eval.intent_router`.

## Known problems and history
- TOOL-12: every action turn failed with HTTP 400 on `gpt-6-luna`, which refuses function tools on
  `/v1/chat/completions` unless `reasoning_effort` is `none`, while `OPENAI_REASONING_EFFORT` (default `low`) was
  sent on every call. `gpt-5-mini` is the opposite (refuses `none`, accepts tools with `low`), so no fixed value
  works → `complete_with_tools_async` uses `OPENAI_TOOL_REASONING_EFFORT` when it offers tools (empty = the answer
  effort); `.env.example` sets `none` for `gpt-6-luna`. The follow-up answer (tool result, no `tools=`) accepts
  `low`. Found by `scripts/eval/tool_selection.py` (EVAL-05), 2026-11-11.
- `chatbot.py` grew too large -> split into routing only (`ChatbotService`), `KnowledgeAnswerer` and
  `TurnDeadline`; the answerer takes a `before_generation` callback so moderation still runs before
  any tokens are generated, and one deadline covers both halves of a turn
  (lcduc/automatic-octo-computing-machines#75, 67254df, 2026-11-10).
- Backend moved under `backend/app`; this folder used to be `core/agent/`
  (lcduc/automatic-octo-computing-machines#76, 06f0477, 2026-11-10).
- Chat shorthands ("có dc ko") hurt routing and search -> `ChatbotService` writes them out
  (`TextUtils.expand_chat_abbreviations`) for router, rewrite and retrieval; the answer prompt keeps
  the visitor's own words. Recall@1 on shorthand input 96.3% -> 98.8%
  (lcduc/automatic-octo-computing-machines#57, baccecf, 2026-10-24).
- Unaccented Vietnamese scored near zero in the reranker ("tien phong o duc" ~0.001 vs ~0.6 accented)
  -> `QueryRewriter` also runs (and restores accents) when a message looks unaccented, even without
  history (code docstring in `query_rewriter.py`).
- A bad rewrite (the light model replying instead of rewriting) hid knowledge -> `KnowledgeAnswerer`
  retries retrieval with the original query when the rewrite matched nothing (code comment).
- Rewrites replayed as chat turns made the model answer or ask back -> history goes in as a quoted
  transcript; human requests get `HUMAN_UNAVAILABLE` when handoff is off instead of a "no information"
  search (lcduc/automatic-octo-computing-machines#23, 7fa0e9e, 2026-09-30).
- Failed-turn apologies replayed as history made the rewriter treat the question as answered ->
  `recent_history` drops messages with outcome `error` (`history.py`).
- Hedged answers from unrelated documents -> the model writes `[NO_ANSWER]` alone and `NoAnswerFilter`
  swallows it before the visitor sees it; the turn takes the fallback/handoff
  (lcduc/automatic-octo-computing-machines#25, e9f71e5, 2026-10-01).
- An empty completion (e.g. a provider safety block) is treated as no answer -> fallback (code comment).
- Newer OpenAI models reject `max_tokens` -> `max_completion_tokens` is sent to every model not in
  `LEGACY_PARAMETER_MODEL_PREFIXES` (lcduc/automatic-octo-computing-machines#23, 87e5b00, 2026-09-30).
- Tool results could carry instructions -> the tool-calling prompt says tool results are data, not
  instructions (lcduc/automatic-octo-computing-machines#22, 869f1a5, 2026-09-29).
- Load tests measured provider latency instead of the app -> `StubClientProvider`
  (`LLM_PROVIDER=stub`); `Config.problems()` makes `APP_ENV=production` refuse it
  (lcduc/automatic-octo-computing-machines#56, af18efb, 2026-10-24).
- OpenAI-compatible local servers need no key -> `OPENAI_BASE_URL` with `LOCAL_SERVER_API_KEY`
  placeholder (lcduc/automatic-octo-computing-machines#63, 56f1039, 2026-10-27).
- `IntentRouter` makes an LLM call per message when tools are offered; the routing spec allows this only
  as deviation DV1 (see [`docs/chatbot-routing-spec.md`](../../../../docs/chatbot-routing-spec.md) §0.1).
  It returns RAG without a call when no tool is offered to the caller.
- `gemini_client.py` and `intent_router.py` docstrings pointed at the old layout (`api/routes/`,
  retrieval in `ChatbotService`); fixed, and the `chatbot.py` ceiling now names its trigger
  (branch `refactor/structure-fixes`, 2026-11-10).
- Windows: scripts that print Vietnamese crash with `UnicodeEncodeError` (cp1252) when output is
  redirected; run them with `PYTHONIOENCODING=utf-8`.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups:
  - TST-09 (docs/checklists/testing.md): no direct unit tests for `TurnDeadline`, `KnowledgeAnswerer` (covered through `ChatbotService`
    in `test_chat_pipeline.py`), `ConfidenceScorer`, `AnthropicClientProvider`, `GeminiClientProvider`.
  - `response_cache.py` docstring still describes caching as part of `ChatbotService` (answers are
    now cached by `KnowledgeAnswerer`).
- Ceilings (`# ceiling:` markers in this folder):
  - `chatbot.py:195` — moderation task not awaited on paths that need no answer still completes in
    the background — cancel it on those paths if moderation API cost or rate limits start to matter.
  - `chatbot.py:305` — the previous clarification is recognised by its fixed text — add a `CLARIFY`
    outcome if admins need to see clarifications as their own outcome.
