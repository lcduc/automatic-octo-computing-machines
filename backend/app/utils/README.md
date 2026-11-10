# `backend/app/utils/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Small, pure, stateless helpers shared across layers: Vietnamese text handling, period/amount
parsing, the request-id context variable, and the Windows asyncio/Uvicorn start-up fixes. Anything
with I/O, configuration of logging, or state belongs in `core/infrastructure/` instead (that is why
`logging_setup` moved out). Domain data classes go in `models/`.

## Files
| File | Public names | What it does |
|---|---|---|
| `text_utils.py` | `TextUtils`, `UNACCENTED_VIETNAMESE_WORDS`, `UNACCENTED_MIN_HITS`, `CHAT_SHORTHANDS`, `SHORTHANDS_KEPT_AFTER_NUMBERS` | Static text helpers: extraction quality (`is_probably_gibberish`, `needs_ocr_fallback`), Vietnamese chat handling (`strip_vietnamese_accents`, `normalize_chat_text`, `looks_like_unaccented_vietnamese`, `expand_chat_abbreviations`), search tokens (`tokenize_for_search`) and sentence chunking (`clean_chunk_text`, `chunk_text`). |
| `vietnamese_parsing.py` | `parse_period`, `parse_amount`, `DateRange` | Parses periods ("tháng trước", "quý 3", "7 ngày qua", "last month", ISO ranges) into `[start, end)` dates and money amounts ("1.000.000 đ", "1,5 triệu", "500k", "3 tỷ") into `Decimal` (TOOL-07). |
| `request_context.py` | `request_id_var`, `current_request_id` | `ContextVar` holding the current HTTP request id; set by `RequestContextMiddleware`, read by logging, error handlers and the audit trail. |
| `asyncio_utils.py` | `setup_windows_asyncio`, `setup_asyncio_logging`, `setup_asyncio_error_handling` | Windows event-loop fixes (SelectorEventLoop policy against WinError 10038/10054) and suppression of the matching asyncio warnings. `main.py` calls the first two, `worker.py` the first; `setup_windows_asyncio` calls the third. |
| `uvicorn_config.py` | `configure_uvicorn_for_windows`, `get_uvicorn_config`, `get_uvicorn_ssl_config` | Uvicorn options (`loop=asyncio`, `http=httptools`, `ws=websockets`) and the Windows loop policy; `get_uvicorn_ssl_config` enables HTTPS when `./SSL/fullchain.pem` and `./SSL/privkey_converted.pem` exist (relative to the working directory). Used by `main.py`. |

## Dependencies
- May import: stdlib and `config` only. Must not import `api`, `services`, `middleware` or `core`
  (layering: api -> services -> core -> models/utils, config at the bottom; enforced by
  `test/unit/test_layering.py`).
- Used by: `text_utils` by document processing, chunking strategies, retrieval, routing, guardrails,
  the chat pipeline and `scripts/eval/`; `vietnamese_parsing` by `core/agent/tools/tool_arguments.py`;
  `request_context` by middleware, `api/` and `core/infrastructure/logging_setup.py`;
  `asyncio_utils`/`uvicorn_config` by the entry points.
- External: none. (`psutil` in `requirements.txt` is used only by `scripts/loadtest/run_levels.py`.)

## Run / test
```bash
pytest test/unit/test_text_utils.py test/unit/test_vietnamese_parsing.py test/unit/test_pdf_ocr_routing.py test/unit/test_guardrails.py
```
On Windows, run scripts that print Vietnamese with `PYTHONIOENCODING=utf-8` when output is
redirected, or they crash with `UnicodeEncodeError` (cp1252).

## Known problems and history
- 9 unused `TextUtils` methods deleted (`text_utils.py` 492 -> 296 lines)
  (lcduc/automatic-octo-computing-machines#73, 64b924d, 2026-11-10).
- `logging_setup` moved from here to `core/infrastructure/logging_setup.py` because `utils` must
  stay pure; its relative `from .request_context` import broke after the move and became absolute
  (#73, d2989b8, 2026-11-10).
- PDFs whose text layer extracts as gibberish are sent to OCR via `is_probably_gibberish` /
  `needs_ocr_fallback` (660c6ce, 2026-09-30).
- Chat shorthands written out before routing and search: 31 unambiguous ones only; ambiguous ones
  (bn, đk, bh, hs, single-letter pronouns) left alone; "k" after a number kept ("500 k"). Recall@1 on
  shorthand-perturbed input rose 96.3% -> 98.8% (baccecf, 2026-10-24).
- Vietnamese period and amount parsing added for the SQL tools (81bb16a, 2026-09-29).
- Backend moved under `backend/app` (#76, 2026-11-10).
- `background_tasks.py` and `monitor.py` (only imported each other) and four unused
  `asyncio_utils.py` helpers deleted (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none.
- Ceilings (`# ceiling:` markers in this folder): `text_utils.py:58` — gibberish check uses
  character categories only, so mis-mapped fonts that decode to real letters pass — add a
  dictionary/language score if they show up.
