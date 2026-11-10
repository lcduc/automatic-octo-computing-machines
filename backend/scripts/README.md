# `backend/scripts/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
One-off command-line tools around the backend: first-time setup, model download, operator commands,
demo data, data conversion, the load test and (in [`eval/`](eval/README.md)) the evals and retrieval
experiments. Scripts import `app.*`, never the other way round: nothing under `app/` imports `scripts`.
Code the running API needs belongs in `app/`; one-off CLIs for the client box's Docker host belong in
`deploy/ops/`.

## Files

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package marker, so scripts run as `python -m scripts.<name>`. |
| `download_models.py` | `ModelDownloader` | Pre-downloads the embedding model, the reranker (and its fallback) and warms PP-OCRv6 into `MODELS_DIR`; the backend Dockerfile runs it at build time. OCR warm-up is best-effort; PaddleOCR-VL (GPU) downloads on first use. |
| `embed_test.py` | `EmbedTestServer`, `main` | Serves a throw-away page on `localhost:8080` that loads a widget's `embed.js` (`--widget`, `--port`), to test embedding from this machine. Its origin must be in `WIDGET_ALLOWED_PARENTS`. |
| `export_openapi.py` | `main` | Builds the FastAPI app without starting it and writes `app.openapi()` to the repo's `docs/openapi.json`. |
| `manage.py` | `ManagementCli`, `main` | Operator CLI: `create-admin`, `bootstrap-admin` (installer; one-time password printed once as JSON), `create-api-key` (default scope `chat`), `test-alert`, `send-alert` (used by the ops CLI on a failed backup), `sync-sql-tools`, `check-business-db`, `export-knowledge`, `import-knowledge`. |
| `qa_to_jsonl.py` | `normalize_header`, `find_columns`, `safe_strify_arguments`, `safe_tool_content`, `build_messages`, `write_jsonl`, `main` | Legacy (2025): converts a Q&A Excel sheet (optionally with function-call columns) into chat-format JSONL for fine-tuning. |
| `qa_to_text_chunks.py` | `normalize_header`, `detect_q_a_columns`, `read_excel_input`, `read_chat_jsonl_input`, `main` | Legacy (2025): turns a Q&A Excel sheet or chat JSONL into `data/chunks/<source>/chunk_NNN.txt` files (`Q: … A: …`). |
| `seed_demo.py` | `DemoSeeder`, `main` | `documents`: writes the demo source and the ten `demo_data/*.md` documents through `KnowledgeService` (skips existing titles). `chats`: runs `demo_data/conversations.json` through the running API with `BFF_SERVICE_TOKEN` (calls the LLM). |
| `setup.py` | `check_python_version`, `install_dependencies`, `create_directories`, `setup_environment`, `main` | First-time local setup: checks Python ≥ 3.10, `pip install -r requirements.txt`, creates `data/logs` and `SSL/`, copies `.env.example` to `.env` if missing. |

All of them run from `backend/` with the backend venv active:

```bash
python -m scripts.setup
python -m scripts.download_models
python -m scripts.manage create-admin --email you@example.com --role owner   # prompts for the password
python -m scripts.manage create-api-key --name "streamlit demo"
python -m scripts.export_openapi
python -m scripts.seed_demo documents        # then restart the API so its index picks them up
python -m scripts.seed_demo chats            # needs the API running and BFF_SERVICE_TOKEN
python -m scripts.embed_test --widget http://localhost:3000 --port 9000
python -m scripts.qa_to_jsonl --input "Q&A.xlsx" --output train_chat.jsonl
python -m scripts.qa_to_text_chunks --input "Q&A.xlsx" --out-root data/chunks
```

### `demo_data/`
Fictional demo content (a Vietnam → Germany labour-migration counselling centre that does not exist) and
the labelled sets the evals and CI read. Not code; nothing here is real visitor data.

| File | What it is |
|---|---|
| `01_cac_con_duong_sang_duc.md` … `10_nganh_thieu_nhan_luc_va_cu_tru_lau_dai.md` | The ten demo knowledge documents `seed_demo documents` loads (heading chunking, `max_chars` 3000). |
| `conversations.json` | 28 demo conversations (`turns`) that `seed_demo chats` sends through the API. |
| `golden_queries.json` | 51 retrieval questions `{query, expected_document}`; `null` document = unanswerable. Used by the CI router gate, the nightly retrieval eval and the load test (`loadtest/locustfile.py` asks these questions). |
| `golden_colloquial_dev.json` | 39 colloquial retrieval questions, the dev split. CI router gate + nightly retrieval eval. |
| `golden_colloquial_holdout.json` | 26 colloquial retrieval questions, the holdout split. CI router gate + nightly retrieval eval. |
| `golden_intents.json` | 60 labelled queries `{query, expected_intent}` (40 rag, 20 action) for `eval/intent_router.py`. |
| `router_eval.json` | 73 labelled messages `{text, intent}` for the embedding router (`eval/router.py`, `eval/robustness.py`). |
| `eval_baseline.json` | Committed regression baselines: one `router` section and one per golden set (recall@k, MRR). Written only by `--write-baseline` and an explicit commit. |
| `synthetic/corpus.jsonl` | The 66 knowledge chunks the synthetic questions were generated from. |
| `synthetic/raw_questions.jsonl` | Every LLM-generated question (396). |
| `synthetic/train.jsonl`, `synthetic/val.jsonl` | Filtered `query` / `positive` pairs (226 / 64) for the adapter and fine-tune experiments. |
| `synthetic/filter_report.json` | What each filter step dropped. |

The layout of `synthetic/` is defined in `eval/synthetic_dataset.py`. The human `golden_*.json` sets are
evaluation-only and are never used for training.

### `loadtest/`
Locust load test of `POST /api/v1/chat/stream`, run against a local API with the stub LLM. Full method and
results: [`docs/PERFORMANCE.md`](../../docs/PERFORMANCE.md).

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package marker (`python -m scripts.loadtest.report`). |
| `locustfile.py` | `WidgetVisitor`, `sse_events` | One simulated visitor = the widget server: service token, own end-user id and forwarded IP, golden questions back to back, honours `Retry-After` on 503/429. Reports `ttft` and `e2e` per turn; tags `X-Request-ID` with `LOADTEST_TAG`. |
| `run_levels.py` | `ResourceSampler`, `LevelRunner`, `env_file_value`, `nvidia_smi`, `other_gpu_jobs`, `wait_for_free_gpu`, `gpu_memory_used_mib`, `main` | Runs Locust at 1/5/10/20/50 users after a warm-up, waits while another job holds the GPU, samples GPU memory/load and API CPU/RSS every 0.5 s into `--out`. |
| `report.py` | `LevelReport`, `percentiles`, `read_csv`, `markdown_table`, `build_report`, `main` | Joins the per-turn CSVs, resource samples and `message_traces.steps_ms` of the run into `results.md`. |
| `loadtest.env` | — | Every API setting the run depends on (stub LLM, port 8600, `MAX_CONCURRENT_CHATS=16`, quotas out of reach); throwaway local values only. |
| `requirements.txt` | — | `locust` only, for its own venv `scripts/loadtest/venv`; never installed into the app venv. |

```bash
python -m dotenv -f scripts/loadtest/loadtest.env run --override -- python -m app.main
python -m venv scripts/loadtest/venv
scripts/loadtest/venv/Scripts/python -m pip install -r scripts/loadtest/requirements.txt
scripts/loadtest/venv/Scripts/python scripts/loadtest/run_levels.py --api-pid <pid> --out data/loadtest/<run>
python -m scripts.loadtest.report data/loadtest/<run>       # app venv
```

## Dependencies
- May import: `app.*` (config, services, core, models). `app/` must never import `scripts`.
- Used by: `backend/Dockerfile` (`download_models`), the installer and ops CLI (`manage bootstrap-admin`,
  `manage send-alert`), CI and `.github/workflows/eval-nightly.yml` (`seed_demo documents`, the golden
  sets), `backend/test/unit/test_eval_*.py` and related unit tests (import `scripts.eval.*`),
  `backend/test/integration/test_sql_tools.py` (reads `deploy/business_db/`, not this folder).
- External: PostgreSQL (`manage`, `seed_demo`, `loadtest/report.py`), Hugging Face model weights
  (`download_models`), the configured LLM (`seed_demo chats`), `nvidia-smi` (`run_levels.py`),
  pandas/openpyxl (`qa_to_*`), locust (load-test venv only).

## Run / test
- Run every script from `backend/` as `python -m scripts.<name>`; loadtest commands as shown above.
- Tests: `backend/test/unit/test_folder_readmes.py` checks every `.py` here is named in this README (or
  `eval/README.md`). The eval modules have their own unit tests (see [`eval/README.md`](eval/README.md)).
- Lint: `ruff check .` from the repo root.

## Known problems and history
- Before #76 the backend lived at the repo root, so these were `scripts/*` at the root; the eval and
  experiment scripts moved into `scripts/eval/` (`lcduc/automatic-octo-computing-machines#76`, 30cfa1c,
  2026-11-10). Script docstrings said "from the repository root" until they were changed to "from
  `backend/`" (branch `refactor/structure-fixes`, 2026-11-10).
- `seed_demo.py` and the Germany demo documents, chats and golden sets were added on 2026-09-30/10-01
  (affa8ce, 13e9671); `eval_baseline.json` came with the CI eval gates (f7f365b, #25).
- `golden_intents.json` was never committed while `eval/intent_router.py` pointed at it; added in a3fa726
  (#54, 2026-10-24).
- Load test (#56, f917e7b, 2026-10-24): on an RTX 3060 with in-process models the knee was ~10 concurrent
  turns at 4.7 turns/s; GPU reranking is the only stage that slowed with load. Details in `docs/PERFORMANCE.md`.
- `synthetic/` was produced by the synthetic-query experiment (#55, 7b055c6); write-up in
  `docs/reports/SYNTHETIC_FINETUNE_RESULTS.md`.
- `embed_test.py` (28576fe, 2026-10-15) defaulted `--widget` to the old VPS demo widget URL; VPS deployment is
  out of scope, so the default is now the local widget dev server `http://localhost:3000`
  (branch `refactor/structure-fixes`, 2026-11-10).
- Windows: scripts that print Vietnamese crash with `UnicodeEncodeError` (cp1252) when output is redirected;
  run with `PYTHONIOENCODING=utf-8`.
- `docs/openapi.json` had drifted from the app; regenerated with `python -m scripts.export_openapi`
  (branch `refactor/structure-fixes`, 2026-11-10).

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: `qa_to_jsonl.py` / `qa_to_text_chunks.py` predate the current
  conventions (no type hints on all functions, `logging.basicConfig` in `qa_to_jsonl.py`).
- Ceilings (`# ceiling:` markers in this folder): none here; see [`eval/README.md`](eval/README.md).
