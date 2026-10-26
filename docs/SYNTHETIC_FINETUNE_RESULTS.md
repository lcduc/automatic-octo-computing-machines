# Synthetic-query training for first-stage retrieval

Experiment on branch `exp/synthetic-finetune` (2026-10-24). Goal: improve the dense (embedding) stage
of retrieval by training on LLM-generated questions, measured only on the human-written golden sets.

**Result.** Fine-tuning `intfloat/multilingual-e5-small` on 226 synthetic pairs raised dense-only
Recall@1 over the 81 answerable golden questions from **70.4% to 81.5%** (mean of 3 seeds; MRR@10
0.812 → 0.892). The gain sits in the dev questions (+12.8 pp); on the 16-question holdout it is
+4.2 pp Recall@1 on average with Recall@5 −4.2 pp, i.e. within noise. The closed-form ridge adapter
made retrieval worse (63.0%). The full stack (BM25 fusion + `bge-reranker-v2-m3`) is already at 97.5%
Recall@1 and does not move with either variant. Neither variant is ready to deploy: both lower the
router's accuracy (84.7% → 77–82%) because its thresholds are absolute cosine values calibrated on the
base model.

## Data

| Step | Count |
|---|---|
| Knowledge chunks (10 demo documents, DB `chatbot`) | 66 |
| Generated questions: 6 per chunk (2 formal, 2 colloquial, 2 unaccented) | 396 |
| − exact duplicates (lower-cased, unaccented, no punctuation) | 0 |
| − near duplicates within a chunk (e5 cosine ≥ 0.95) | 6 |
| − overlap with any golden question (exact or e5 cosine ≥ 0.93), dropped as possible leakage | 45 |
| − round trip failed: source chunk not in the reranker's top 3 of all 66 chunks | 46 (35 unaccented, 8 colloquial, 3 formal) |
| − over 5 per chunk (styles take turns, reranker order) | 9 |
| **Kept** | **290** (111 formal, 93 colloquial, 86 unaccented) |
| Train / validation (1 held-out question per chunk with ≥ 3) | 226 / 64 |

- Generator: OpenAI `gpt-6-luna` (reasoning effort low) through the project's provider classes;
  66 calls, 33,274 prompt + 29,957 completion tokens, about **$0.02** at $0.10 / $0.50 per million
  (third-party list price). The golden questions were never shown to the LLM.
- 65 of 66 chunks have questions. The uncovered one is the "Chọn con đường nào?" summary table,
  whose content repeats other chunks (its questions failed the round trip or overlapped a golden question).
- The reranker rejects unaccented questions most often, so the kept set under-represents that style.
- Files: `scripts/demo_data/synthetic/` (`corpus.jsonl`, `raw_questions.jsonl`, `train.jsonl`,
  `val.jsonl`, `filter_report.json` with every golden overlap listed).

## Variants

**(a) Ridge adapter** (`core/retrieval/query_adapter.py`, `scripts/build_query_adapter.py`): closed-form
A = (QᵀQ + λI)⁻¹QᵀP from the 226 training pairs, λ chosen on the synthetic validation questions only.

| λ | none | 0.001 | 0.01 | **0.1** | 1 | 10 | 100 |
|---|---|---|---|---|---|---|---|
| Validation chunk MRR@10 | **0.630** | 0.384 | 0.478 | 0.528 | 0.223 | 0.067 | 0.040 |

No λ beats the unadapted model. With 226 pairs in 384 dimensions the ridge solution shrinks query
directions outside the training span to zero. A scratch check of the identity prior
(A = (QᵀQ + λI)⁻¹(QᵀP + λI)) reached only 0.630 vs 0.628, so the limit is the MSE regression objective,
not the regularizer. A contrastively trained linear head would be the fair adapter baseline.

**(b) Fine-tune** (`scripts/finetune_embedding_model.py`): sentence-transformers
`MultipleNegativesRankingLoss` (scale 20), batch 32 with no chunk twice in a batch, AdamW lr 2e-5,
10% warm-up, E5 `query:` / `passage:` prompts, early stopping on validation chunk MRR@10 (patience 2),
best epoch's weights kept. A plain PyTorch loop: `SentenceTransformerTrainer` needs the `datasets`
package, which the project does not install. Under a minute per run on the RTX 3060.

| Seed | Best epoch (of run) | Validation chunk MRR@10 (base 0.628) |
|---|---|---|
| 13 | 3 (5) | 0.754 |
| 21 | 4 (6) | 0.761 |
| 42 | 6 (8) | 0.761 |

The fine-tuned KB was re-embedded in a copy of the database (`chatbot_ft`); `chatbot` still holds
base-model vectors.

## Results on the human golden sets

Document level, `top_k` 10 chunks, answerable questions only. Dev = `golden_queries` (40, formal) +
`golden_colloquial_dev` (25); holdout = `golden_colloquial_holdout` (16). Nothing was tuned on either:
λ and the stopping epoch came from the synthetic validation split. One holdout question = 6.25 pp.

### Dense only (cosine ranking, no BM25, no reranker)

| Variant | Dev R@1 | Dev R@5 | Dev MRR@10 | Holdout R@1 | Holdout R@5 | Holdout MRR@10 | All R@1 | All R@5 | All MRR@10 |
|---|---|---|---|---|---|---|---|---|---|
| Baseline e5-small | 70.8% | 95.4% | 0.811 | 68.8% | 100.0% | 0.818 | 70.4% | 96.3% | 0.812 |
| (a) Ridge adapter, λ=0.1 | 63.1% | 96.9% | 0.777 | 62.5% | 93.8% | 0.742 | 63.0% | 96.3% | 0.770 |
| (b) Fine-tune, seed 13 | 86.2% | 100.0% | 0.924 | 68.8% | 93.8% | 0.786 | 82.7% | 98.8% | 0.897 |
| (b) Fine-tune, seed 21 | 83.1% | 100.0% | 0.908 | 75.0% | 93.8% | 0.823 | 81.5% | 98.8% | 0.891 |
| (b) Fine-tune, seed 42 | 81.5% | 100.0% | 0.897 | 75.0% | 100.0% | 0.854 | 80.2% | 100.0% | 0.889 |
| (b) Fine-tune, mean of 3 | 83.6% | 100.0% | 0.910 | 72.9% | 95.8% | 0.821 | 81.5% | 99.2% | 0.892 |

Per golden set (dense, R@1): formal 77.5% → 85.0–90.0%; colloquial dev 60.0% → 72.0–80.0%;
colloquial holdout 68.8% → 68.8–75.0%. Seed 13 on holdout: 3 questions improved, 5 got worse, and one
unaccented question ("chi phi ve may bay mot chieu sang Duc…") fell out of the top 10.

### Full stack (live semantic weight, BM25 fusion, `bge-reranker-v2-m3`)

| Variant | Dev R@1 / R@5 / MRR@10 | Holdout R@1 / R@5 / MRR@10 | All R@1 / R@5 / MRR@10 |
|---|---|---|---|
| Baseline | 96.9% / 100% / 0.985 | 100% / 100% / 1.000 | 97.5% / 100% / 0.988 |
| (a) Ridge adapter | 96.9% / 100% / 0.985 | 100% / 100% / 1.000 | 97.5% / 100% / 0.988 |
| (b) Fine-tune, all 3 seeds | 96.9% / 100% / 0.985 | 100% / 100% / 1.000 | 97.5% / 100% / 0.988 |

The reranker scores a pool of 30 of the 66 chunks, which already holds the answer for every question,
so the dense stage only matters here when the reranker is off or fails (the cosine fallback) and on
a larger corpus where the pool is a smaller share.

### Router check (`scripts/eval_router.py` + all three golden sets, 189 messages)

| Variant | Accuracy | Greeting | Thanks | Handoff | Ambiguous | Off-topic caught | Questions stolen | Questions refused if retrieval is empty |
|---|---|---|---|---|---|---|---|---|
| Baseline | 84.7% | 7/7 | 6/6 | 6/6 | 7/8 | 12/40 | 0 | 2 |
| (a) Ridge adapter | 77.2% | 1/7 | 0/6 | 3/6 | 5/8 | 16/40 | 1 | 0 |
| (b) Fine-tune, seed 13 | 81.5% | 7/7 | 6/6 | 2/6 | 7/8 | 10/40 | 0 | 7 |
| (b) Fine-tune, seeds 21 / 42 | 79.4% | 4/7 | 5/6 | 2/6 | 7/8 | 10/40 | 0 | 8 |

`eval_router.py` now loads the configured query adapter, as the app does before building the router;
before this change the adapter row would have silently measured the unadapted model.

## Overfitting risk with 66 chunks

- **The gain is tied to this corpus.** The encoder embeds both the questions and the 66 passages, and
  training pulls each passage towards the questions about it. That is what helps the golden questions,
  and it does not carry over to documents added later: every knowledge-base change needs a regenerate
  → filter → retrain → re-embed cycle (cheap here, about $0.02 and a minute of GPU, but it must be automated).
- **Validation is in-distribution.** The early-stopping questions come from the same LLM and the same
  chunks as the training questions, so they guard against over-training on synthetic text, not against
  corpus memorization. Validation MRR rose 0.63 → 0.76; the human dev gain (+12.8 pp R@1) is real, but
  the holdout (+4.2 pp R@1, −4.2 pp R@5, MRR +0.003 on average) cannot separate a small gain from none.
- **Same facts, different words.** With 66 chunks, synthetic and human questions necessarily ask about
  the same facts. Synthetic questions within e5 cosine 0.93 of any golden question were dropped (45),
  so the test questions were not paraphrased into training, but dev and holdout are still "seen
  passages, unseen questions", not unseen documents.
- **The similarity scale moves.** Fine-tuning spreads the cosine distribution (lowest RAG-question score
  against the route examples: 0.82 → 0.30–0.50). Every absolute cosine threshold calibrated on the base
  model goes stale: the router's route thresholds (accuracy 84.7% → 79–82%, handoff requests 6/6 → 2/6)
  and `SEMANTIC_THRESHOLD`, the cosine gate used when the reranker is unavailable (not re-calibrated here).
- **Style bias.** The round trip drops unaccented questions most, so the training set leans formal;
  the one new holdout miss is an unaccented question.
- **Small-sample noise.** Three seeds disagree by up to 4.7 pp on dev R@1 and 6.25 pp on holdout R@1.

## Before deploying the fine-tune

1. Re-calibrate the router thresholds and `SEMANTIC_THRESHOLD` for the new model (`scripts/eval_router.py`,
   `scripts/eval_rag.py`), or keep the base model for routing.
2. Grow the holdout well beyond 16 questions (it decides the go / no-go), ideally with real chat logs.
3. Automate retraining whenever the knowledge base changes.

## Reproduce

From the repository root with the venv active, `DATABASE_URL` pointing at the seeded demo database,
and the models in `MODELS_DIR`:

```bash
python -m scripts.generate_synthetic_queries --model gpt-6-luna      # LLM_PROVIDER=openai, OPENAI_API_KEY set
python -m scripts.filter_synthetic_queries
python -m scripts.build_query_adapter --output data/adapters/query_adapter_synthetic.npy --force  # no lambda beats the base model, so it refuses without --force
python -m scripts.finetune_embedding_model --seed 13 --output model_weights/finetuned/multilingual-e5-small-synthetic
python -m scripts.eval_retrieval_variants --label baseline
QUERY_ADAPTER_PATH=data/adapters/query_adapter_synthetic.npy python -m scripts.eval_retrieval_variants --label adapter
# the fine-tune needs its own database copy: CREATE DATABASE chatbot_ft TEMPLATE chatbot;
DATABASE_URL=.../chatbot_ft EMBEDDING_MODEL=<abs path to the fine-tuned model> python -m scripts.eval_retrieval_variants --label finetune --allow-reembed
python -m scripts.eval_router --golden-set scripts/demo_data/golden_queries.json --golden-set scripts/demo_data/golden_colloquial_dev.json --golden-set scripts/demo_data/golden_colloquial_holdout.json
```

`eval_retrieval_variants` refuses a database embedded with another model unless `--allow-reembed` is
given, because starting the app re-embeds stale chunks in place.
