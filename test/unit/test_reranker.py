"""Unit tests for the reranker's model loading (fake transformers, no weights)."""

from core.retrieval import reranker
from core.retrieval.reranker import RERANKER_FALLBACK_MODEL, Reranker

PRIMARY = "BAAI/bge-reranker-v2-m3"


class FakeModel:
    """Enough of a transformers model for the cross-encoder wrapper to wrap."""

    def to(self, _device):
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


def test_no_reranker_when_neither_loads(monkeypatch):
    _fake_transformers(monkeypatch, unavailable={PRIMARY, RERANKER_FALLBACK_MODEL})
    assert not Reranker(PRIMARY).available()
