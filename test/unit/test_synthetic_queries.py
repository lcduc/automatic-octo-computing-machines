import random

import numpy as np
import pytest

from scripts.eval_rag import QueryResult
from scripts.eval_retrieval_variants import metrics
from scripts.filter_synthetic_queries import MAX_KEPT_PER_CHUNK, SyntheticQueryFilter, normalized, split
from scripts.finetune_embedding_model import no_duplicate_batches
from scripts.generate_synthetic_queries import parse_questions
from scripts.synthetic_dataset import chunk_mrr


def test_parse_questions_reads_fenced_json_and_drops_unknown_styles():
    reply = 'Here:\n```json\n{"questions": [{"style": "Formal", "question": " Lương  bao nhiêu? "}, {"style": "poem", "question": "x"}]}\n```'
    assert parse_questions(reply) == [{"style": "formal", "question": "Lương bao nhiêu?"}]


def test_parse_questions_rejects_a_reply_without_questions():
    with pytest.raises(ValueError):
        parse_questions("Xin lỗi, tôi không thể giúp.")


def test_normalized_matches_accented_and_unaccented_forms():
    assert normalized("Học nghề ở Đức mất bao lâu?") == normalized("hoc nghe o duc mat bao lau")


def test_chunk_mrr_scores_ranks_and_zero_beyond_k():
    corpus = np.eye(3)
    queries = np.array([[1.0, 0.0, 0.0], [0.9, 0.5, 0.0]])
    # Query 0 ranks chunk 0 first; query 1 ranks its target (chunk 1) second.
    assert chunk_mrr(queries, corpus, [0, 1]) == pytest.approx((1 + 0.5) / 2)
    assert chunk_mrr(queries, corpus, [0, 1], k=1) == pytest.approx(0.5)


def test_batches_never_repeat_a_chunk_and_keep_every_pair():
    pairs = [{"chunk_id": f"c{i % 5}", "query": str(i)} for i in range(23)]
    batches = no_duplicate_batches(pairs, batch_size=4, rng=random.Random(0))
    assert all(len({p["chunk_id"] for p in batch}) == len(batch) <= 4 for batch in batches)
    assert sorted(p["query"] for batch in batches for p in batch) == sorted(p["query"] for p in pairs)


def test_cap_keeps_styles_balanced_in_reranker_order():
    records = [
        {"chunk_id": "c", "style": style, "question": f"{style}{n}", "rerank_score": score}
        for style, scores in {"formal": (0.9, 0.8, 0.7), "colloquial": (0.6, 0.5), "unaccented": (0.4, 0.3)}.items()
        for n, score in enumerate(scores)
    ]
    kept = SyntheticQueryFilter(None, None, [], [])._cap_per_chunk(records)
    assert len(kept) == MAX_KEPT_PER_CHUNK
    assert [r["question"] for r in kept] == ["formal0", "colloquial0", "unaccented0", "formal1", "colloquial1"]


def test_split_holds_out_one_question_only_for_chunks_with_enough():
    corpus = [{"chunk_id": "a", "document_title": "A", "content": "text a"}, {"chunk_id": "b", "document_title": "B", "content": "text b"}]
    records = [
        {"chunk_id": chunk, "style": "formal", "question": f"{chunk}{n}", "rerank_rank": 1, "rerank_score": 0.9}
        for chunk, count in (("a", 4), ("b", 2))
        for n in range(count)
    ]
    train, val = split(records, corpus)
    assert [pair["chunk_id"] for pair in val] == ["a"]
    assert len(train) == 5 and all(pair["positive"] == f"text {pair['chunk_id']}" for pair in train + val)


def test_metrics_count_answerable_questions_only():
    results = [
        QueryResult("q1", "Doc", [], 1, None, 0.0),
        QueryResult("q2", "Doc", [], 4, None, 0.0),
        QueryResult("q3", "Doc", [], None, None, 0.0),
        QueryResult("q4", None, [], None, None, 0.0, "off_topic"),
    ]
    scores = metrics(results)
    assert scores["answerable"] == 3
    assert scores["recall_at_1"] == pytest.approx(1 / 3)
    assert scores["recall_at_5"] == pytest.approx(2 / 3)
    assert scores["mrr"] == pytest.approx((1 + 0.25) / 3)
