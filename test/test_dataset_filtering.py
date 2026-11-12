"""Regression tests for chatting with one journal of data_chatbot.7z (?id=<JOURNAL>)."""

import numpy as np
import pytest

from core.ai_services.llm.prompts import PromptManager
from core.ai_services.translation import JOURNAL_ABBREVIATIONS, build_translation_input
from core.retrieval.search.retriever import ContextRetriever
from core.retrieval.similarity.similarity import SimilarityCalculator
from core.storage.metadata_stores.document_store import DocumentStore
from core.storage.metadata_stores.metadata_store import MetadataStore

# The folders of data_chatbot.7z, one per VNU journal.
ARCHIVE_JOURNALS = ["CSCE", "EAB", "EES", "ER", "FS", "LS", "MAP", "MPS", "NST", "PAM", "SSH"]


class _FakeEmbedder:
    """Embeds every query as [1, 0]."""

    def encode(self, texts, convert_to_numpy=True):
        return np.array([[1.0, 0.0]])

    def apply_query_adapter(self, embedding):
        return embedding


class _FakeIndex:
    def __init__(self, ntotal):
        self.ntotal = ntotal


class _FakeStore:
    """A whole store of `ntotal` chunks whose FAISS hit is at global position `hit`."""

    def __init__(self, ntotal, hit):
        self.faiss_index = _FakeIndex(ntotal)
        self.document_metadata = [{"source_id": "X"}] * ntotal
        self._hit = hit
        self.faiss_calls = 0

    def fast_similarity_search(self, query_embedding, k):
        self.faiss_calls += 1
        return np.array([0.99]), np.array([self._hit])

    def get_metadata(self):
        return self.document_metadata

    def load_vector_store(self):
        return None


def _retriever(store):
    retriever = ContextRetriever.__new__(ContextRetriever)
    retriever.embedding_service = _FakeEmbedder()
    retriever.vector_store = store
    retriever.similarity_calculator = SimilarityCalculator()
    retriever.reranker = None
    retriever.clear_cache()
    retriever._query_preprocessing_cache = {}
    return retriever


def test_a_filtered_search_scores_its_own_chunks_not_the_global_faiss_index(monkeypatch):
    monkeypatch.setenv("USE_FAISS_INDEX", "true")
    store = _FakeStore(ntotal=99, hit=42)
    documents = ["alpha chunk", "beta chunk"]

    results = _retriever(store).hybrid_search("beta", np.array([[0.0, 1.0], [1.0, 0.0]]), documents, k=2)

    beta = next(r for r in results if r["document"] == "beta chunk")
    assert store.faiss_calls == 0 and beta["semantic_score"] == pytest.approx(1.0)


def test_an_unfiltered_search_still_uses_faiss(monkeypatch):
    monkeypatch.setenv("USE_FAISS_INDEX", "true")
    store = _FakeStore(ntotal=2, hit=1)

    _retriever(store).hybrid_search("beta", np.array([[0.0, 1.0], [1.0, 0.0]]), ["alpha", "beta"], k=2)

    assert store.faiss_calls == 1


@pytest.mark.parametrize("code", ARCHIVE_JOURNALS)
def test_every_journal_has_a_name_for_chat_and_translation(code):
    bot_name, scope = PromptManager()._resolve_journal_scope(code.lower())

    assert scope.endswith(f"(JS:{code})") and bot_name == scope
    assert f"journal_code: {code}" in build_translation_input("Text.", journal_code=code)
    assert JOURNAL_ABBREVIATIONS[code] == f"JS:{code}"


def test_an_empty_chunk_file_keeps_metadata_aligned_with_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNKS_DIR", str(tmp_path))
    for journal, files in {"LS": ["Law text", "   \n"], "SSH": ["Social text"]}.items():
        (tmp_path / journal).mkdir()
        for number, text in enumerate(files, start=1):
            (tmp_path / journal / f"chunk_{number:03d}.txt").write_text(text, encoding="utf-8")

    documents = DocumentStore().load_documents_from_chunks()
    metadata = MetadataStore().create_metadata_from_chunks(documents)

    assert [m["source_id"] for m in metadata] == ["LS", "SSH"] and len(documents) == 2
