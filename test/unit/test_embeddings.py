"""Unit tests for the in-process embedding service (a fake model, no weights)."""

import numpy as np
import pytest

from core.retrieval import embeddings
from core.retrieval.embeddings import EmbeddingService


class RecordingModel:
    """Stands in for SentenceTransformer: applies ``prompts`` as the real one does and records what it encoded."""

    loaded = []
    seen = []

    def __init__(self, model_name, device, cache_folder, prompts=None):
        RecordingModel.loaded.append((model_name, device))
        self.prompts = prompts or {}

    def _encode(self, texts, prefix):
        RecordingModel.seen.extend(prefix + text for text in texts)
        return np.ones((len(texts), 3), dtype=np.float32)

    def encode_query(self, texts, **_kwargs):
        return self._encode(texts, self.prompts.get("query", ""))

    def encode_document(self, texts, **_kwargs):
        return self._encode(texts, self.prompts.get("document", ""))


@pytest.fixture
def fake_model(monkeypatch):
    RecordingModel.loaded, RecordingModel.seen = [], []
    monkeypatch.setattr(embeddings, "SentenceTransformer", RecordingModel)
    monkeypatch.setattr(embeddings, "torch", None)  # CPU only
    return RecordingModel


def test_e5_queries_and_passages_get_their_trained_prefixes(fake_model, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    service = EmbeddingService()

    service.embed_query("giờ làm việc")
    service.embed_passages(["Giờ làm việc từ 8h đến 17h."])

    assert fake_model.seen == ["query: giờ làm việc", "passage: Giờ làm việc từ 8h đến 17h."]


def test_a_model_without_known_prompts_embeds_raw_text(fake_model, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    service = EmbeddingService()

    service.embed_query("giờ làm việc")

    assert fake_model.seen == ["giờ làm việc"]


def test_a_model_that_fails_to_load_raises_instead_of_falling_back_to_another(monkeypatch):
    attempted = []

    def failing_model(model_name, **_kwargs):
        attempted.append(model_name)
        raise OSError("weights unavailable")

    monkeypatch.setattr(embeddings, "SentenceTransformer", failing_model)
    monkeypatch.setattr(embeddings, "torch", None)
    monkeypatch.setenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

    with pytest.raises(RuntimeError, match="multilingual-e5-small"):
        EmbeddingService().get_embedder()
    assert attempted == ["intfloat/multilingual-e5-small"]
