# Code quality checklist

Is the code easy to read, change and extend safely? Rules come from `CLAUDE.md`; this file records
whether the repository actually meets them.

Last assessed: 2026-11-10 at `2c55f4e`.

## Structure

- [x] CQ-01 Dependency direction `api → services → core → models/utils` holds, and only the HTTP layer (`api`, `middleware`) imports FastAPI/Starlette — enforced by `backend/test/unit/test_layering.py`, relative imports included
- [x] CQ-02 Every module under `app/` and `scripts/` is named in its folder README — enforced by `backend/test/unit/test_folder_readmes.py`
- [~] CQ-03 No file over ~400 lines — five over: `api/schemas/admin.py` (500), `services/knowledge_service.py` (445), `core/storage/knowledge_repository.py` (445), `services/auth_service.py` (435), `services/chat_service.py` (407). Split each when it is next changed, not as a standalone refactor
- [x] CQ-04 One concern per file, config only in `app/config/`, prompts and canned replies only in `core/agent/prompts.py`
- [~] CQ-05 No dead code — unused modules and helpers removed in PR #85 (`utils/background_tasks.py`, `utils/monitor.py`, four `asyncio_utils` helpers, `normalize_legacy_metadata`); nothing detects new dead code automatically

## Linting and typing

- [x] CQ-06 Python lint in CI and a required check — `ruff check .` (`ruff.toml`), job `Lint (ruff)`
- [ ] CQ-07 Lint rules beyond pyflakes/pycodestyle — `ruff.toml` selects only `E`, `F`, `W`; adding `B` (bugbear) would catch mutable defaults, loop-variable closures and `except` mistakes
- [ ] CQ-08 Python types checked — hints are written everywhere (`CLAUDE.md` §1) but no mypy/pyright runs, so nothing verifies them
- [x] CQ-09 Frontends lint and type-check in CI — widget `eslint` + `tsc --noEmit`, admin `oxlint --deny-warnings` + `tsc --noEmit` (`.github/workflows/ci.yml`)
- [-] CQ-10 Code formatter enforced — `ruff.toml` deliberately leaves formatting off; adopt only with one repo-wide format commit, never file by file
- [~] CQ-11 No deprecated APIs in use — `models/metadata.py:36` uses Pydantic's class-based `Config`, deprecated in v2 and removed in v3 (pytest warns on every run)

## Error handling and logging

- [~] CQ-12 Every `except` logs or re-raises (`CLAUDE.md` §4) — 124 of 148 handlers in `app/` do; 24 do neither. Most are intended (optional imports in `embeddings.py`/`reranker.py`/`docling_processor.py`, cancellation in `sse.py`, parse fallbacks in `text_utils.py`/`vietnamese_parsing.py`), but each should say so in a comment or log at `DEBUG`. Found with an AST scan for `ExceptHandler` bodies without `logger.*` or `raise`
- [x] CQ-13 No debug `print()` in `app/` — only the startup banner in `main.py` (intentional operator output)
- [x] CQ-14 No `TODO`/`FIXME`; deliberate limits use `# ceiling:` markers with a trigger (14 in `app/`), each listed in its folder README's Status

## Documentation and developer experience

- [x] CQ-15 Every folder has a README with Files, Known problems and history, and Status (`CLAUDE.md` §0)
- [~] CQ-16 `docs/openapi.json` matches the app — regenerated in PR #85 (`scripts/export_openapi.py`); no CI step fails when it drifts
- [~] CQ-17 Setup instructions match the checkout — `CLAUDE.md` §3 says `backend/venv`; the working checkout uses `venv/` at the repository root
- [ ] CQ-18 Contributor files — no `CONTRIBUTING.md`, `CODEOWNERS`, pull-request template or `.editorconfig`
