"""Unit tests for hybrid retrieval over a knowledge snapshot (no model weights)."""

import uuid

import numpy as np

from core.retrieval.knowledge_index import KnowledgeSnapshot
from core.retrieval.retriever import RRF_K, ContextRetriever
from core.storage.knowledge_repository import IndexRow

DOC_A = uuid.uuid4()
DOC_B = uuid.uuid4()


def _row(document_id, position, content, embedding, source="general", priority=1.0, title="Doc"):
    return IndexRow(
        chunk_id=uuid.uuid4(),
        document_id=document_id,
        position=position,
        content=content,
        embedding=embedding,
        chunk_metadata={},
        document_title=title,
        document_metadata={"url": "https://example.test"},
        original_filename=None,
        source_name=source,
        source_priority=priority,
    )


class FakeEmbeddings:
    """Returns a fixed query vector."""

    def __init__(self, vector):
        self._vector = np.asarray(vector, dtype=np.float32)

    def embed_query(self, query):
        return self._vector / np.linalg.norm(self._vector)


class FakeReranker:
    """Scores texts by whether they contain a keyword."""

    def __init__(self, keyword):
        self._keyword = keyword

    def score(self, query, texts):
        return [0.9 if self._keyword in text else 0.05 for text in texts]


def _snapshot():
    rows = [
        _row(DOC_A, 0, "intro chapter", [0.0, 1.0, 0.0]),
        _row(DOC_A, 1, "salary policy details", [1.0, 0.0, 0.0]),
        _row(DOC_A, 2, "closing remarks", [0.0, 0.0, 1.0]),
        _row(DOC_B, 0, "faq about salary", [0.9, 0.1, 0.0], source="FAQ", title="FAQ"),
    ]
    return KnowledgeSnapshot.build(rows, version=1)


def _search(retriever, snapshot, **overrides):
    params = dict(
        top_k=2, semantic_weight=0.7, threshold=0.5, semantic_threshold=0.5, max_context_chunks=6,
        expansion_radius=1, sources=None,
    )
    params.update(overrides)
    return retriever.search("salary", snapshot, **params)


def test_snapshot_merges_document_and_chunk_metadata_and_indexes_sources():
    snapshot = _snapshot()
    assert snapshot.chunks[0].metadata["url"] == "https://example.test"
    assert set(snapshot.source_indices) == {"general", "FAQ"}
    assert np.allclose(np.linalg.norm(snapshot.embeddings, axis=1), 1.0)


def test_nothing_above_threshold_returns_empty_so_caller_can_fall_back():
    retriever = ContextRetriever(FakeEmbeddings([0, 1, 0]), FakeReranker("nonexistent"))
    assert _search(retriever, _snapshot()) == []


def test_match_is_expanded_with_same_document_neighbours_in_order():
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), FakeReranker("salary policy"))
    results = _search(retriever, _snapshot(), top_k=1)
    contents = [item.chunk.content for item in results]
    assert contents == ["intro chapter", "salary policy details", "closing remarks"]
    assert [item.matched for item in results] == [False, True, False]


def _ranked_snapshot(documents=4):
    """``documents`` docs of filler / answer / filler; answer ``d`` ranks d-th."""
    rows = []
    for rank in range(documents):
        document_id = uuid.uuid4()
        rows += [
            _row(document_id, 0, f"before {rank}", [0.0, 1.0, 0.0]),
            _row(document_id, 1, f"answer {rank}", [1.0, 0.05 * rank, 0.0]),
            _row(document_id, 2, f"after {rank}", [0.0, 0.0, 1.0]),
        ]
    return KnowledgeSnapshot.build(rows, version=1)


def test_only_the_best_match_is_expanded_and_the_other_matches_follow_by_rank():
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=None)
    results = _search(retriever, _ranked_snapshot(), top_k=4, max_context_chunks=6)
    assert [item.chunk.content for item in results] == [
        "before 0", "answer 0", "after 0", "answer 1", "answer 2", "answer 3",
    ]
    assert [item.matched for item in results] == [False, True, False, True, True, True]


def test_a_tight_cap_drops_neighbours_before_matches():
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=None)
    results = _search(retriever, _ranked_snapshot(), top_k=4, max_context_chunks=5)
    assert [item.chunk.content for item in results] == ["before 0", "answer 0", "answer 1", "answer 2", "answer 3"]


def test_a_neighbour_that_is_also_a_match_keeps_its_place_and_match_data_once():
    rows = [
        _row(DOC_A, 0, "salary policy", [1.0, 0.0, 0.0]),
        _row(DOC_A, 1, "salary table", [0.9, 0.1, 0.0]),
        _row(DOC_A, 2, "closing remarks", [0.0, 0.0, 1.0]),
    ]
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=None)
    results = _search(retriever, KnowledgeSnapshot.build(rows, version=1), top_k=2)
    assert [(item.chunk.content, item.matched) for item in results] == [("salary policy", True), ("salary table", True)]


def test_a_chunk_missing_from_the_index_leaves_no_false_neighbour():
    # Position 1 is not indexed (e.g. no embedding), so position 2 is not adjacent to 0.
    rows = [_row(DOC_A, 0, "salary policy", [1.0, 0.0, 0.0]), _row(DOC_A, 2, "closing remarks", [0.0, 0.0, 1.0])]
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=None)
    results = _search(retriever, KnowledgeSnapshot.build(rows, version=1), top_k=1)
    assert [item.chunk.content for item in results] == ["salary policy"]


def test_neighbours_never_cross_document_boundaries():
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), FakeReranker("faq about"))
    results = _search(retriever, _snapshot(), top_k=1)
    assert [item.chunk.content for item in results] == ["faq about salary"]


def test_source_filter_restricts_candidates():
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), FakeReranker("salary"))
    results = _search(retriever, _snapshot(), sources=["FAQ"], expansion_radius=0)
    assert {item.chunk.source for item in results} == {"FAQ"}
    assert _search(retriever, _snapshot(), sources=["missing"]) == []


def test_source_priority_reorders_equally_relevant_matches():
    rows = [
        _row(DOC_A, 0, "salary general", [1.0, 0.0, 0.0], source="general", priority=1.0),
        _row(DOC_B, 0, "salary faq", [1.0, 0.0, 0.0], source="FAQ", priority=2.0),
    ]
    snapshot = KnowledgeSnapshot.build(rows, version=1)
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), FakeReranker("salary"))
    results = _search(retriever, snapshot, expansion_radius=0)
    assert [item.chunk.source for item in results] == ["FAQ", "general"]


def test_reranker_sees_the_document_title_with_each_chunk():
    # "Which university did Luong Chi Duc attend?" vs an EDUCATION chunk that never names him:
    # only the document title says whose CV it is.
    rows = [_row(DOC_A, 0, "## EDUCATION\nSwinburne University", [1.0, 0.0, 0.0], title="CV Luong Chi Duc")]
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=FakeReranker("Luong Chi Duc"))

    results = _search(retriever, KnowledgeSnapshot.build(rows, version=1), expansion_radius=0)

    assert [item.chunk.content for item in results] == ["## EDUCATION\nSwinburne University"]


def test_without_reranker_gates_on_the_semantic_threshold():
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=None)
    results = _search(retriever, _snapshot(), threshold=0.0, semantic_threshold=0.999, expansion_radius=0)
    assert [item.chunk.content for item in results] == ["salary policy details"]


class FailingReranker:
    """A reranker whose scoring failed: returns ``None`` like ``Reranker.score`` does."""

    def score(self, query, texts):
        return None


def test_a_failed_reranker_gates_on_the_semantic_threshold_not_the_reranker_one():
    # A reranker threshold of 0.3 on cosine scores would let the unrelated FAQ chunk (0.99) and more through.
    retriever = ContextRetriever(FakeEmbeddings([1, 0, 0]), reranker=FailingReranker())
    results = _search(retriever, _snapshot(), threshold=0.3, semantic_threshold=0.999, expansion_radius=0)
    assert [item.chunk.content for item in results] == ["salary policy details"]


def test_reciprocal_rank_fusion_uses_ranks_and_ignores_keyword_misses():
    values = np.array([0.2, 9.0, 0.0, 3.0])
    ranks = ContextRetriever._reciprocal_ranks(values, values > 0)
    assert ranks[1] == 1 / (RRF_K + 1) and ranks[3] == 1 / (RRF_K + 2) and ranks[0] == 1 / (RRF_K + 3)
    assert ranks[2] == 0.0  # no keyword match, no contribution
    # A huge outlier score earns no more than first place (min-max scaling would squash the rest).
    outlier = ContextRetriever._reciprocal_ranks(np.array([1000.0, 3.0, 2.0]), np.ones(3, dtype=bool))
    assert outlier[0] == 1 / (RRF_K + 1) and outlier[1] == 1 / (RRF_K + 2)
