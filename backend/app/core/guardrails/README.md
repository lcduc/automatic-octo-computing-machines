# `backend/app/core/guardrails/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Cheap, rule-based screening of user text: prompt-injection and human-request detection, pure
greetings/thanks, sensitive-topic matching, an optional moderation call, and PII redaction before
text is stored or logged. Nothing here calls an LLM directly; the moderator is injected.
Meaning-based routing (off-topic, ambiguous) belongs in [`../routing/`](../routing/); the order in
which checks run is decided by `ChatbotService` in [`../agent/`](../agent/).

## Files

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package docstring only. |
| `input_guard.py` | `InputGuard`, `GuardAction`, `GuardVerdict`, `Moderator` | `classify_rules` matches injection, human-request, greeting and thanks patterns on lower-cased, accent-free text (no network); `is_flagged` calls the injected moderator and fails open. |
| `pii_redactor.py` | `PiiRedactor`, `RedactionResult`, `TAG_EMAIL`, `TAG_PHONE`, `TAG_ID`, `TAG_CARD`, `TAG_BANK_ACCOUNT`, `TAG_TAX_CODE`, `TAG_PASSPORT`, `TAG_BIRTH_DATE`, `MIN_CARD_DIGITS`, `MAX_CARD_DIGITS` | `redact` masks e-mails, VN phone numbers, CCCD/CMND, Luhn-valid card numbers, and keyword-gated bank account, tax code, passport and birth date; returns text plus per-tag counts. |
| `topic_matcher.py` | `matching_topic` | First admin-configured sensitive topic (HND-06) found as whole words, ignoring case and accents. |

## Dependencies
- May import: `app.utils.text_utils` only (accent stripping, chat-text normalization). Layering:
  api -> services -> core -> models/utils; config at the bottom; only main.py imports middleware;
  enforced by `test/unit/test_layering.py`.
- Used by: `core/agent/chatbot.py` (`InputGuard`, `matching_topic`), `app/api/container.py`
  (builds `InputGuard` with `OpenAIClientProvider.moderate` when `MODERATION_ENABLED`, and `PiiRedactor`
  when `PII_REDACTION_ENABLED`), `services/chat_service.py` (redacts the stored user message),
  `services/eval_case_service.py` (always redacts), `core/infrastructure/logging_setup.py` (log filter).
- External: none in this folder; the moderator passed in is OpenAI's moderation endpoint.

## Run / test
From `backend/` with `venv` active:
```
pytest test/unit/test_guardrails.py      # redaction, injection, human requests, greetings, moderation fail-open
pytest -m red_team -v                    # test_red_team.py prompt-injection suite (a CI step)
ruff check .                             # from the repo root
```
`InputGuard` is also exercised through the pipeline in `test_chat_pipeline.py`,
`test_chat_turn_recovery.py`, `test_chatbot_action_routing.py` and `test_embedding_router.py`.
`matching_topic` has no dedicated test.

## Known problems and history
- Missed attacks ("forget your instructions", role-play, "what are your instructions") and false
  blocks on questions about exam instructions -> patterns widened, and only the bot's own
  instructions count (lcduc/automatic-octo-computing-machines#22, cb54ee5, 2026-09-29, SEC-01).
- Sensitive topics should go to staff, not to the bot -> `topic_matcher.py` added with handoff on
  sensitive topics (lcduc/automatic-octo-computing-machines#22, df94960, 2026-09-29, HND-06).
- Injection phrases hidden with invisible or look-alike characters -> visitor messages are
  normalised before matching (`TextUtils.normalize_chat_text`)
  (lcduc/automatic-octo-computing-machines#25, 9193a50, 2026-10-01; covered by `test_guardrails.py`).
- Passport numbers and dates of birth were stored unmasked -> keyword-gated rules added
  (5b3b8a3, 2026-10-22).
- Ordinary numbers such as salaries must not be masked -> bank account, tax code, passport, birth date
  and 9-digit CMND only match next to their keywords; card numbers must pass Luhn (module docstring).
- A moderation outage must not block real users -> `is_flagged` logs and returns `False` on any error.
  `ChatbotService` starts it as a task that overlaps routing and retrieval and awaits it only right
  before generation (see [`../agent/README.md`](../agent/README.md)).
- Backend moved under `backend/app`; this folder used to be `core/guardrails/`
  (lcduc/automatic-octo-computing-machines#76, 06f0477, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: names and addresses are not recognized by `PiiRedactor` (stated in its
  docstring); `matching_topic` has no unit test.
- Ceilings (`# ceiling:` markers in this folder): none.
