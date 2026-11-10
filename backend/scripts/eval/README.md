# `backend/scripts/eval/`

<!-- Keep this README true. Anyone (person or agent) who adds, removes or renames a file here,
     or hits a problem worth remembering, updates the matching section in the same PR. -->

## Purpose
Offline evals of the chat pipeline (router, retrieval, end-to-end outcomes) and the retrieval experiments
behind them (synthetic training data, query adapter, embedding fine-tune, robustness to messy Vietnamese).
They run the real `app.*` code against the labelled sets in [`../demo_data/`](../README.md#demo_data).
Nothing under `app/` imports this package. Demo data and the golden sets live in `../demo_data/`; the load
test lives in `../loadtest/`.

## Files

**Where each one runs**
- **CI, every PR** (`.github/workflows/ci.yml`, job `test`): `router.py --check` over the three golden
  sets — fails when a real question is taken by a shortcut or accuracy drops past the tolerance in
  `baseline.py`. Needs only the small embedding model (cached); no LLM, no database, no secrets.
- **Nightly** (`.github/workflows/eval-nightly.yml`, 02:00 Vietnam time, also on demand): `rag.py --check`,
  one matrix job per golden set (`golden_colloquial_dev`, `golden_colloquial_holdout`, `golden_queries`),
  after `alembic upgrade head` and `seed_demo documents` on a fresh pgvector database. No LLM.
- **Manual** experiments: everything else. Scripts that call the LLM cost money: `chat_outcomes.py`,
  `intent_router.py`, `generate_synthetic_queries.py`.
- **Helpers** (no CLI): `baseline.py`, `synthetic_dataset.py`, `threshold_calibrator.py`, `vietnamese_perturber.py`.

| File | Public names | What it does |
|---|---|---|
| `__init__.py` | — | Package marker (`python -m scripts.eval.<name>`). |
| `baseline.py` | `EvalBaseline` | Reads/writes `../demo_data/eval_baseline.json` and checks a report against it. Tolerances: router fails on any stolen question, or accuracy drop > max(2 points, 2 messages); retrieval fails if recall@k falls below baseline at all or MRR drops > 0.02. A changed eval set means re-record. |
| `router.py` | `RouterEvaluator`, `golden_to_router_cases`, `print_report`, `main` | **CI gate.** Embedding-router accuracy, confusion matrix, questions stolen by shortcuts, off-topic signals and score ranges on `router_eval.json` (+ `--golden-set`, repeatable). `--check` / `--write-baseline`. |
| `rag.py` | `QueryResult`, `RetrievalEvaluator`, `calibration`, `build_report`, `print_report`, `load_golden_set`, `run`, `main` | **Nightly gate.** Recall@k / MRR of the live retriever with the relevance gates off, plus calibration of `SIMILARITY_THRESHOLD` and `SEMANTIC_THRESHOLD`. `--check` / `--write-baseline`. Shared evaluator for the other retrieval scripts. |
| `chat_outcomes.py` | `OutcomeEvaluator`, `print_report`, `main` | End-to-end: golden questions through the real chat pipeline and LLM; answerable should be answered, `unanswerable` handed to staff, `off_topic` refused. Default sets: dev + holdout. Calls the LLM. |
| `compare_configs.py` | `RetrievalRunConfig`, `comparison_configs`, `ConfigComparisonRunner`, `compare`, `print_comparison`, `main` | One golden set through `dense_only`, `hybrid`, `hybrid_rerank` and (if `QUERY_ADAPTER_PATH` is set) `hybrid_rerank_adapter`, in one process. Needs `MODEL_SERVER_URL` empty. |
| `retrieval_variants.py` | `metrics`, `VariantEvaluator`, `stored_embedding_models`, `run`, `print_report`, `main` | Recall@1/@5 and MRR@10 of whatever embedding variant the env configures, dense-only and full stack, per golden set and dev/holdout group. Refuses a database embedded with another model unless `--allow-reembed`. |
| `robustness.py` | `RetrievalConfig`, `RetrievalRobustness`, `load_router_cases`, `load_answerable`, `router_metrics`, `as_searched`, `variants`, `score_retrieval`, `print_tables`, `main` | Router and retrieval (dense, BM25, hybrid, full) on clean input and under every perturbation of `vietnamese_perturber.py`. Needs the demo knowledge base seeded. |
| `router_classifier.py` | `CachedEmbeddings`, `LogisticRouteClassifier`, `RouterCrossValidation`, `print_table`, `main` | Nested stratified CV: the production nearest-example router vs logistic regression on the same e5 embeddings, clean and perturbed. |
| `intent_router.py` | `IntentRoutingEvaluator`, `load_golden_set`, `print_report`, `main` | Accuracy of the LLM `IntentRouter` (rag vs action) on `golden_intents.json`, with the live tool registry. Exits 1 if any call silently fell back to rag. Calls the LLM. |
| `hardware_divergence.py` | `HardwareDivergenceEvaluator`, `print_report`, `main` | Encodes the same queries with the embedding model on GPU and on CPU and reports the per-query cosine divergence. Needs CUDA. |
| `threshold_calibrator.py` | `ThresholdRates`, `ThresholdCalibrator` | Picks the relevance threshold that best separates answerable from unanswerable questions (used by `rag.py`). |
| `vietnamese_perturber.py` | `VietnamesePerturber`, `telex_keys` | Seeded, order-independent perturbations: `no_diacritics`, `abbreviations`, `telex`, `typos`, `no_spaces`, `chat_mix`. |
| `synthetic_dataset.py` | `read_jsonl`, `write_jsonl`, `chunk_mrr` | File layout of `../demo_data/synthetic/` and the chunk-level MRR@10 the training scripts select on. |
| `generate_synthetic_queries.py` | `user_prompt`, `parse_questions`, `SyntheticQueryGenerator`, `export_corpus`, `main` | Exports the chunk corpus and has the configured LLM write formal / colloquial / unaccented questions per chunk (`--dry-run`, `--limit`, `--model`). Calls the LLM. |
| `filter_synthetic_queries.py` | `normalized`, `rerank_text`, `SyntheticQueryFilter`, `split`, `load_golden_queries`, `main` | Drops exact/near duplicates, anything close to a human golden question, and questions that fail a reranker round trip; caps per chunk; splits train / val. |
| `build_query_adapter.py` | `QueryAdapterBuilder`, `main` | Fits the closed-form linear query adapter on train pairs, picks lambda on val, writes `QUERY_ADAPTER_PATH`. Refuses an adapter that loses to the unadapted model unless `--force`. |
| `finetune_embedding_model.py` | `no_duplicate_batches`, `EmbeddingFineTuner`, `main` | Fine-tunes multilingual-e5-small on the synthetic pairs (`MultipleNegativesRankingLoss`, plain PyTorch loop, early stopping on val MRR@10). |

**Synthetic pipeline:** `generate_synthetic_queries` → `filter_synthetic_queries` → `build_query_adapter` or
`finetune_embedding_model` → score with `retrieval_variants` (never on the synthetic data itself).

## Dependencies
- May import: `app.*` and other `scripts.eval.*` modules. Imports must be `from scripts.eval import x` /
  `from scripts.eval.x import y`. `app/` must never import this package.
- Used by: `.github/workflows/ci.yml` (`router.py`), `.github/workflows/eval-nightly.yml` (`rag.py`),
  `app/config/settings.py` and `app/core/routing/embedding_router.py` (comments naming the calibration
  scripts), the unit tests below.
- External: embedding model and `BAAI/bge-reranker-v2-m3` weights (`model_weights/`), PostgreSQL with the
  seeded demo knowledge base (`rag`, `compare_configs`, `retrieval_variants`, `robustness`, `chat_outcomes`),
  the configured LLM provider (`chat_outcomes`, `intent_router`, `generate_synthetic_queries`), CUDA
  (`hardware_divergence`), scikit-learn (`router_classifier`), sentence-transformers / torch (fine-tune).

## Run / test
Run from `backend/` with the venv active. On Windows set `PYTHONIOENCODING=utf-8` first (Vietnamese output
crashes cp1252 consoles when redirected).

```bash
python -m scripts.eval.router --check --golden-set scripts/demo_data/golden_colloquial_dev.json \
  --golden-set scripts/demo_data/golden_colloquial_holdout.json --golden-set scripts/demo_data/golden_queries.json
python -m scripts.eval.rag --check --golden-set scripts/demo_data/golden_queries.json
python -m scripts.eval.rag --write-baseline --golden-set scripts/demo_data/golden_queries.json   # then commit eval_baseline.json
python -m scripts.eval.chat_outcomes --out logs/outcomes.json
python -m scripts.eval.compare_configs --golden-set scripts/demo_data/golden_colloquial_holdout.json --k 10
python -m scripts.eval.retrieval_variants --label baseline --out logs/variants/baseline.json
python -m scripts.eval.robustness --only router
python -m scripts.eval.router_classifier
python -m scripts.eval.intent_router
python -m scripts.eval.hardware_divergence --golden-set scripts/demo_data/golden_queries.json
python -m scripts.eval.generate_synthetic_queries --dry-run
python -m scripts.eval.filter_synthetic_queries
python -m scripts.eval.build_query_adapter
python -m scripts.eval.finetune_embedding_model --output model_weights/finetuned/e5-small-synthetic
```

Unit tests (`backend/test/unit/`): `test_eval_baseline.py`, `test_eval_compare_configs.py`,
`test_eval_intent_router.py`, `test_query_adapter.py`, `test_synthetic_queries.py`,
`test_threshold_calibrator.py`, `test_vietnamese_perturber.py`. Run with `pytest test/unit -k "eval or
query_adapter or synthetic or threshold or perturber"`.

## Known problems and history
- Moved here from `scripts/` with the `eval_` prefix dropped (`eval_rag.py` → `rag.py`, `eval_router.py` →
  `router.py`, …) in `lcduc/automatic-octo-computing-machines#76` (30cfa1c, 2026-11-10). Two
  `from scripts import ...` forms were missed at first and fixed to `from scripts.eval import ...`.
  Docstrings said "from the repository root" and `baseline.py` named `eval_router` / `eval_rag` until
  they were changed to "from `backend/`" and `scripts.eval.router` / `scripts.eval.rag`
  (branch `refactor/structure-fixes`, 2026-11-10).
- CI eval gates and committed baselines added in #25 (f7f365b, 2026-10-01).
- Nightly retrieval eval: the CPU reranker costs ~20 s per question, so one sequential job took ~42 of its
  45 minutes and 9 of 10 runs were cancelled → one matrix job per golden set, 40-minute budget,
  `fail-fast: false` (c9d1283, #54, 2026-10-24).
- `intent_router.py`: `IntentRouter.classify()` returns `(intent, usage)` but the eval called `.value` on the
  tuple, and its default golden set was never committed; a missing API key scored 66.7% because failed
  calls default to rag → unpacked the pair, added `golden_intents.json`, count fallbacks and exit 1
  (a3fa726, #54). Its docstring pointed at `ChatbotService.__init__`; it now points at
  `AppContainer.start` in `app/api/container.py`, where the live registry is built (branch `refactor/structure-fixes`).
- `compare_configs.py` failed on import (removed vector store, old `RetrievalEvaluator` / `ContextRetriever`
  signatures) → rebuilt on `rag.py`'s evaluator; clears the start-up adapter for runs that don't ask for it and
  refuses a remote model-server, which applies its own adapter (d361ae6, #54).
- `router.py` skipped loading `QUERY_ADAPTER_PATH`, so with an adapter configured it measured the
  unadapted model → loads it as the app does (b1b7bf2, #55).
- Synthetic experiment (#55, 7b055c6): fine-tuned e5-small raised dense-only Recall@1 70.4% → 81.5% but the
  router dropped to 79–82% (thresholds calibrated on the base model); the ridge adapter was worse at every
  lambda; full stack stayed at 97.5%. Hence `build_query_adapter.py --force`. Write-up:
  [`docs/reports/synthetic-finetune-results.md`](../../../docs/reports/synthetic-finetune-results.md).
- Robustness (#57, b937ee8): missing accents is the costliest perturbation, only for the embedding model
  (dense Recall@1 57 → 13 of 81). Logistic regression doubled off-topic coverage on clean input but stole real
  questions on messy input, so the nearest-example rule stays. Write-up:
  [`docs/reports/eval-robustness.md`](../../../docs/reports/eval-robustness.md).
- `hardware_divergence.py` defaulted to a golden set that does not exist; the default is now
  `scripts/demo_data/golden_queries.json` (branch `refactor/structure-fixes`, 2026-11-10).
- Windows: Vietnamese output raises `UnicodeEncodeError` (cp1252) when redirected → `PYTHONIOENCODING=utf-8`.

## Status
- Last reviewed: 2026-11-10
- Open issues / follow-ups: none.
- Ceilings (`# ceiling:` markers in this folder): `finetune_embedding_model.py:60` — quadratic greedy batch
  fill, fine for a few thousand pairs — use a per-chunk queue beyond that.
