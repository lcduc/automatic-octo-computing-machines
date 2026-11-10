# Robustness to messy Vietnamese input

Measured 2026-10-24 on branch `eval/vi-robustness`. "Before" is the branch base `a82183a`; "after" is this branch.
Everything below runs on synthetic variants of the existing eval sets. No real visitor data is used.

## What is measured

- **Router:** the 189 labelled messages of the router eval (`router_eval.json` plus the three golden sets, labelled as `eval_router` does): 122 real questions, 40 off-topic, 27 small-talk/handoff. Reported: accuracy, macro-F1 over the six routes, real questions stolen by a shortcut (the costliest error), off-topic caught.
- **Retrieval:** the 81 answerable golden questions over the demo knowledge base (10 documents, 66 chunks). Document level, top 10 chunks: Recall@1, Recall@5, MRR@10.
  - `dense` (SEMANTIC_WEIGHT=1.0), `bm25` (0.0), `hybrid` (0.7), no reranker. Scored on the order of the fused score itself, the order the reranker's pool is cut from. The live no-reranker path re-sorts its pool by cosine, which makes the weight nearly irrelevant there: R@1 57, 57 and 58 of 81 at weights 1.0, 0.7 and 0.0.
  - `full` (0.7 + bge-reranker-v2-m3): the live `ContextRetriever.search` with the relevance gates off.
- Models: multilingual-e5-small (fp16) and bge-reranker-v2-m3 on an RTX 3060. No LLM calls. In production, Vietnamese typed without accents is sent to an LLM rewrite that restores them, when `looks_like_unaccented_vietnamese` fires. That rewrite is not in this eval, so the no-accent retrieval numbers are the floor for when it is skipped or fails. The last table shows how often it would fire.

### Perturbations

`scripts/vietnamese_perturber.py`, seed 13. Each variant depends only on the seed, the perturbation and the text, so it never changes when cases are added or reordered.

| name | what | "Học nghề ở Đức có được trả lương không vậy anh?" |
|---|---|---|
| `no_diacritics` | NFD, combining marks dropped, đ → d | Hoc nghe o Duc co duoc tra luong khong vay anh? |
| `abbreviations` | 38 words and phrases replaced at every occurrence by one of 55 chat shorthands (không → ko/k/hok/kh, được → dc/đc/đk, gì → j, vậy → v/z …) | Học nghề ở Đức có đk trả lương hok z a? |
| `telex` | 30% of accented words left as raw Telex keys (được → dduwowcj) | Học nghề ở Đức có được trả luwowng không vậy anh? |
| `typos` | 5% of letters dropped or swapped with the next letter | Học nghề  Đức có được trả lơng khôg vậy anh? |
| `no_spaces` | 30% of spaces dropped | Họcnghềở Đức cóđược trả lươngkhông vậy anh? |
| `chat_mix` | abbreviations, then no diacritics | Hoc nghe o Duc co dc tra luong kh z a? |

The rates were fixed before the first run, not tuned.

## Results: before → after

### Router (189 messages: 122 questions, 40 off-topic)

| input | accuracy | macro-F1 | questions stolen | off-topic caught |
|---|---|---|---|---|
| clean | 84.7% (160) → 84.7% (160) | 0.881 → 0.881 | 0 → 0 | 12 → 12 |
| no_diacritics | 74.1% (140) → **86.2% (163)** | 0.642 → **0.830** | 0 → 0 | 0 → **19** |
| abbreviations | 83.6% (158) → **84.1% (159)** | 0.860 → **0.866** | 0 → 0 | 11 → **12** |
| telex | 77.8% (147) → **78.3% (148)** | 0.720 → **0.733** | 0 → 0 | 6 → 6 |
| typos | 83.6% (158) → 83.6% (158) | 0.856 → 0.856 | 0 → 0 | 11 → 11 |
| no_spaces | 79.9% (151) → 79.9% (151) | 0.766 → 0.766 | 0 → 0 | 8 → 8 |
| chat_mix | 73.0% (138) → **85.7% (162)** | 0.620 → **0.817** | 0 → 0 | 0 → **19** |

Clean decisions are identical, message by message. The CI gate (`eval_router --check`) passes at 84.7% with 0 stolen.

### Retrieval (81 answerable questions; hits in brackets)

| input | config | R@1 | R@5 | MRR@10 |
|---|---|---|---|---|
| clean | dense | 70.4% (57) → 70.4% (57) | 96.3% (78) → 96.3% (78) | 0.812 → 0.812 |
| clean | bm25 | 75.3% (61) → 75.3% (61) | 98.8% (80) → 98.8% (80) | 0.855 → 0.855 |
| clean | hybrid | 77.8% (63) → 77.8% (63) | 98.8% (80) → 98.8% (80) | 0.868 → 0.868 |
| clean | full | 97.5% (79) → 97.5% (79) | 100.0% (81) → 100.0% (81) | 0.988 → 0.988 |
| no_diacritics | dense | 16.0% (13) → 16.0% (13) | 67.9% (55) → 67.9% (55) | 0.344 → 0.344 |
| no_diacritics | bm25 | 75.3% (61) → 75.3% (61) | 98.8% (80) → 98.8% (80) | 0.855 → 0.855 |
| no_diacritics | hybrid | 30.9% (25) → 30.9% (25) | 82.7% (67) → 82.7% (67) | 0.519 → 0.519 |
| no_diacritics | full | 70.4% (57) → 70.4% (57) | 96.3% (78) → 96.3% (78) | 0.804 → 0.804 |
| abbreviations | dense | 65.4% (53) → **66.7% (54)** | 95.1% (77) → **96.3% (78)** | 0.785 → **0.796** |
| abbreviations | bm25 | 74.1% (60) → *72.8% (59)* | 98.8% (80) → *97.5% (79)* | 0.843 → *0.838* |
| abbreviations | hybrid | 74.1% (60) → **76.5% (62)** | 97.5% (79) → **98.8% (80)** | 0.845 → **0.864** |
| abbreviations | full | 96.3% (78) → **98.8% (80)** | 100.0% (81) → 100.0% (81) | 0.981 → **0.994** |
| telex | dense | 63.0% (51) → 63.0% (51) | 96.3% (78) → 96.3% (78) | 0.760 → 0.760 |
| telex | bm25 | 70.4% (57) → 70.4% (57) | 97.5% (79) → 97.5% (79) | 0.816 → 0.816 |
| telex | hybrid | 72.8% (59) → 72.8% (59) | 97.5% (79) → 97.5% (79) | 0.835 → 0.835 |
| telex | full | 93.8% (76) → 93.8% (76) | 100.0% (81) → 100.0% (81) | 0.967 → 0.967 |
| typos | dense | 63.0% (51) → 63.0% (51) | 93.8% (76) → 93.8% (76) | 0.764 → 0.764 |
| typos | bm25 | 69.1% (56) → 69.1% (56) | 96.3% (78) → 96.3% (78) | 0.811 → 0.811 |
| typos | hybrid | 74.1% (60) → **75.3% (61)** | 96.3% (78) → 96.3% (78) | 0.844 → **0.851** |
| typos | full | 96.3% (78) → 96.3% (78) | 98.8% (80) → 98.8% (80) | 0.975 → 0.975 |
| no_spaces | dense | 67.9% (55) → 67.9% (55) | 95.1% (77) → 95.1% (77) | 0.782 → 0.782 |
| no_spaces | bm25 | 51.9% (42) → 51.9% (42) | 88.9% (72) → 88.9% (72) | 0.666 → 0.666 |
| no_spaces | hybrid | 66.7% (54) → 66.7% (54) | 97.5% (79) → 97.5% (79) | 0.797 → 0.797 |
| no_spaces | full | 93.8% (76) → 93.8% (76) | 100.0% (81) → 100.0% (81) | 0.964 → 0.964 |
| chat_mix | dense | 17.3% (14) → **18.5% (15)** | 70.4% (57) → *69.1% (56)* | 0.362 → *0.360* |
| chat_mix | bm25 | 74.1% (60) → 74.1% (60) | 98.8% (80) → *97.5% (79)* | 0.843 → **0.845** |
| chat_mix | hybrid | 38.3% (31) → *35.8% (29)* | 82.7% (67) → **85.2% (69)** | 0.566 → *0.557* |
| chat_mix | full | 67.9% (55) → **70.4% (57)** | 93.8% (76) → **95.1% (77)** | 0.783 → **0.798** |

Bold is better, italics worse. Clean is identical in every config. Only abbreviation expansion touches retrieval: it helps the configuration production runs (`full`) on both inputs it targets. It moves the fusion-only rankers by a question or two either way.

| input | LLM accent-restoring rewrite would fire (of 81) |
|---|---|
| clean | 7 → 7 (golden questions already typed without accents) |
| no_diacritics | 77 → 77 |
| chat_mix | 70 → **75** |
| other inputs | unchanged (7, 7, 7, 4) |

## What changed

1. **Router examples are also matched without accents** (`core/routing/embedding_router.py`, `with_accent_free_forms`). Each example gets an accent-free copy at load time, so `routes.json` stays single-spelling. `handoff_request` is left out. The guard's accent-free patterns already catch unaccented handoff requests. With handoff copies included, two long unaccented questions were routed to a handoff, at 0.902 and 0.909 against the 0.90 threshold; every correct handoff scored at least 0.914. Result: no-accent accuracy 74.1% → 86.2%, off-topic caught 0 → 19 of 40, nothing stolen.
2. **Chat shorthands are written out before routing and search** (`TextUtils.expand_chat_abbreviations`, used by `ChatbotService`). The answer prompt and the stored message keep the visitor's own words.
   - **Dictionary:** 31 shorthands with one clear meaning. Ambiguous ones are left alone: bn = bao nhiêu or bạn; đk = được, điều kiện or đăng ký; bh = bây giờ or bảo hiểm; hs = hồ sơ or học sinh; plus tt, tl, ts, đt, s and the single-letter pronouns. "k" is kept after a number ("500 k").
   - **Accent style:** an unaccented message gets unaccented full forms ("co dc ko" → "co duoc khong"), so it still triggers the accent-restoring rewrite (70 → 75 of 81 on chat_mix).
   - **Clean text:** none of the 429 clean texts (eval cases and route examples) changes.
   - **Dotted and hyphenated tokens:** a shorthand inside one is left alone, so "v.v." (etc.) and "J-1" keep their meaning, while a sentence-final "ko." is still written out. This was added in review; the shorthand runs above give identical numbers with it.

## Tried and not kept

| option | result | why not kept |
|---|---|---|
| Accent-insensitive BM25 | Already in place: `TextUtils.tokenize_for_search` folds accents on both the index and the query, so BM25 scores are identical with and without accents (61/80/0.855) | nothing to add |
| Accent-free copies for `handoff_request` too | No accents: 87.3% (165) instead of 86.2% (163) | 2 real questions stolen |
| Logistic regression router (`scripts/eval_router_classifier.py`) | See below. Clean 92.6% vs 85.7%, off-topic caught 27 vs 14 | steals 1–2 real questions under 4 of 6 perturbations; the rule steals none |
| Reranker compares an unaccented query with unaccented passages | full R@1 no accents 57 → 61, chat_mix 57 → 59; but clean 79 → 78, telex 76 → 75, abbreviations 80 → 79 | hurts clean input |

### Router classifier: nested stratified cross-validation

5 outer folds over the 189 messages, seed 0. Each fold trains on `routes.json` plus the other four folds, with the same accent-free copies for both methods, and tests on the held-out fold, clean and perturbed. Logistic regression is class-balanced and multinomial, on the e5 embeddings. It takes a shortcut only above a probability floor. `C` and the floor are chosen per fold by a 3-fold inner CV on clean input: fewest stolen questions first, then accuracy. The chosen settings were C=30 with p ≥ 0.7, or C=100 with p ≥ 0.8.

| input | nearest example: accuracy, stolen, off-topic | logistic regression: accuracy, stolen, off-topic |
|---|---|---|
| clean | 85.7% (162), 0, 14 | **92.6% (175)**, 0, **27** |
| no_diacritics | 86.2% (163), 0, 19 | 85.7% (162), *1*, 21 |
| abbreviations | 85.2% (161), 0, 14 | **91.5% (173)**, 0, **27** |
| telex | 78.8% (149), 0, 6 | **87.8% (166)**, *2*, **26** |
| typos | 83.6% (158), 0, 12 | **87.3% (165)**, *2*, **25** |
| no_spaces | 80.4% (152), 0, 9 | **86.2% (163)**, *1*, **25** |
| chat_mix | 85.7% (162), 0, 19 | 85.7% (162), 0, 20 |

Logistic regression roughly doubles off-topic coverage, but on messy input it takes real questions as shortcuts, which the router is built never to do. A variant that also counted stolen questions on perturbed validation input when choosing settings was tried during development; it is not kept in the script. It became too conservative: 83.6% on clean input, and it still stole a question in 5 of 6 perturbed inputs. The nearest-example rule stays.

## Findings

- **Missing accents is the costliest perturbation, and only for the embedding model.** Dense R@1 falls from 57 to 13 of 81. The full stack falls from 79 to 57: the reranker recovers most, not all. BM25 is unaffected. The LLM rewrite covers this in production (it fires on 77 of 81), at the price of an LLM call before every such search.
- **Missing spaces mostly hurt BM25** (R@1 61 → 42) and barely touch dense retrieval.
- **The router never steals a question under any perturbation.** It fails safe: perturbed shortcuts and off-topic messages go to retrieval instead.

## Caveats

- Synthetic perturbations at a single seed. 81 and 189 cases: one question is 1.2 points of recall, one message 0.5 points of accuracy.
- The expander writes out 31 of the perturber's 55 shorthand forms, so part of the `abbreviations` gain is by construction. The other 24 forms are untouched.
- A typo can create a shorthand: "Đức" with a dropped letter ("Đc") is written out as "được". It cost nothing here, since "Đc" never matched Đức anyway.
- "đc" is occasionally shorthand for "địa chỉ" (address), not "được". The dictionary treats it as "được", the common reading; watch real chat logs for address questions it misreads.
- The demo knowledge base is small: the reranker's pool is 40 of 66 chunks.

## Follow-ups

- Dense retrieval without accents (R@1 70% → 16%): accent-free passage embeddings, or accent restoration without an LLM.
- A Telex leftover decoder. It needs a syllable lexicon: English words decode to valid syllables (bus → bú, tax → tã, how → hơ).
- Logistic regression router: double the off-topic coverage on clean input, if a safety floor that holds on messy input can be found.
- Measure with the LLM rewrite in the loop.

## Reproduce

From the repository root with the venv active, the demo knowledge base seeded (`python -m scripts.seed_demo documents`), and `DATABASE_URL` set:

```bash
python -m scripts.eval_robustness --out logs/robustness.json
python -m scripts.eval_router_classifier --out logs/router_classifier.json
```

`--only router|retrieval` and `--perturbation <name>` narrow the run. The router part needs no database.
