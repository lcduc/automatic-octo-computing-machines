"""Unit tests for the reranker's model loading (fake transformers, no weights)."""

import types

from core.retrieval import reranker
from core.retrieval.reranker import RERANK_BATCH_SIZE, RERANKER_FALLBACK_MODEL, Reranker

PRIMARY = "BAAI/bge-reranker-v2-m3"


class FakeModel:
    """Enough of a transformers model for the cross-encoder wrapper to wrap."""

    def to(self, _device):
        return self

    def half(self):
        return self

    def eval(self):
        return self


def _fake_transformers(monkeypatch, unavailable):
    """Patch the transformers loaders; models in ``unavailable`` fail to load. Returns the attempted names."""
    attempted = []

    class FakeLoader:
        @staticmethod
        def from_pretrained(name, **_kwargs):
            attempted.append(name)
            if name in unavailable:
                raise OSError(f"{name} unavailable")
            return FakeModel()

    monkeypatch.setattr(reranker, "AutoTokenizer", FakeLoader, raising=False)
    monkeypatch.setattr(reranker, "AutoModelForSequenceClassification", FakeLoader, raising=False)
    monkeypatch.setattr(reranker, "TRANSFORMERS_AVAILABLE", True)
    return attempted


def test_the_primary_reranker_loads_when_available(monkeypatch):
    attempted = _fake_transformers(monkeypatch, unavailable=set())
    loaded = Reranker(PRIMARY)
    assert loaded.available() and loaded._model_name == PRIMARY
    assert RERANKER_FALLBACK_MODEL not in attempted


def test_the_multilingual_fallback_loads_when_the_primary_cannot(monkeypatch, caplog):
    _fake_transformers(monkeypatch, unavailable={PRIMARY})
    loaded = Reranker(PRIMARY)
    assert loaded.available() and loaded._model_name == RERANKER_FALLBACK_MODEL
    assert "running on fallback" in caplog.text


def test_scoring_runs_in_batches_of_the_configured_size(monkeypatch):
    import torch

    _fake_transformers(monkeypatch, unavailable=set())
    sizes = []

    class FakeTokenizer:
        def __call__(self, queries, documents, **_kwargs):
            sizes.append(len(queries))
            return types.SimpleNamespace(to=lambda _device: {"n": len(queries)})

    class FakeScorer(FakeModel):
        def __call__(self, n):
            return types.SimpleNamespace(logits=torch.zeros(n, 1))

    wrapper = Reranker(PRIMARY)._create_cross_encoder_wrapper(FakeScorer(), FakeTokenizer())
    scores = wrapper.predict([("q", f"d{i}") for i in range(RERANK_BATCH_SIZE * 2 + 3)])
    assert sizes == [RERANK_BATCH_SIZE, RERANK_BATCH_SIZE, 3] and len(scores) == RERANK_BATCH_SIZE * 2 + 3


def test_no_reranker_when_neither_loads(monkeypatch):
    _fake_transformers(monkeypatch, unavailable={PRIMARY, RERANKER_FALLBACK_MODEL})
    assert not Reranker(PRIMARY).available()
