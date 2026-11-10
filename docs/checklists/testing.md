# Testing checklist

Do the tests prove the code works, and do they run on every change? Evaluation of answer quality
(golden sets, retrieval metrics) is in [production.md](production.md) §17; this file covers the
test suites themselves.

Last assessed: 2026-11-10 at `2c55f4e`.

## What CI runs

- [x] TST-01 Backend unit and integration tests run on every PR against a real pgvector database — job `Tests (pytest)`, 443 tests, a required check
- [x] TST-02 Migrations apply, roll back and re-apply on an empty database — `alembic upgrade head && alembic downgrade base && alembic upgrade head` in CI
- [x] TST-03 Hard gates (EVAL-09) and the red-team set (SEC-01) run as their own CI steps — `pytest -m hard_gate`, `pytest -m red_team`
- [x] TST-04 Router regression gate on every PR; retrieval eval nightly — `scripts.eval.router --check` in `ci.yml`, `eval-nightly.yml`
- [x] TST-05 Ops CLI tests — `deploy/ops/tests`, job `Ops CLI tests (pytest)`

## Coverage

- [~] TST-06 Coverage measured and tracked — 83% of lines in `app/` (10,257 statements, 1,697 missed), measured locally with `coverage run --source=app -m pytest` against pgvector; not in CI, so a drop goes unnoticed
- [ ] TST-07 The real upload path is tested — `core/document_processing/main_processor.py` and `processors.py` are at 0%: every test injects a fake processor, so `MainDocumentProcessor` (used by `api/container.py` and `worker.py`) never runs. One integration test parsing a small PDF and DOCX through it would cover the entry point
- [~] TST-08 Process entry points tested — `worker.py` and `model_server.py` are at 0% (their services are tested; the wiring is not)
- [ ] TST-09 Non-default LLM providers tested — `anthropic_client.py` 28%, `gemini_client.py` 32%, `openai_client.py` 54%; no direct unit tests for `TurnDeadline` or `ConfidenceScorer` (73%) either

## Reliability

- [~] TST-10 No flaky tests — `integration/test_api.py::test_rate_limit_and_roles` depends on the per-minute rate-limit window and passes on rerun (`backend/test/README.md`)

## Frontends

- [~] TST-11 Frontend logic tested — widget 3 and admin 8 Vitest files run in CI; no browser-level test of the embed, chat stream or admin login
- [-] TST-12 Streamlit demo tested — internal demo only (`frontends/streamlit/README.md`), not a product
