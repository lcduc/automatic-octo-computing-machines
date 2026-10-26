"""Unit tests for the in-process embedding service (a fake model, no weights)."""

import sys
import threading
import time

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


#: Long enough that every thread reaches the model load before the first one finishes it.
SLOW_LOAD_SECONDS = 0.2
#: Threads racing on the same service.
RACING_THREADS = 8


def _run_concurrently(target, *, threads: int = RACING_THREADS) -> list:
    """Start ``threads`` threads on ``target(index)`` at the same moment; return what they raised."""
    barrier = threading.Barrier(threads)
    errors = []

    def run(index):
        barrier.wait()
        try:
            target(index)
        except Exception as error:  # collected for the assertion, not swallowed
            errors.append(error)

    workers = [threading.Thread(target=run, args=(index,)) for index in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return errors


def test_concurrent_first_queries_load_the_model_once(fake_model, monkeypatch):
    class SlowModel(RecordingModel):
        def __init__(self, *args, **kwargs):
            time.sleep(SLOW_LOAD_SECONDS)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(embeddings, "SentenceTransformer", SlowModel)
    monkeypatch.setenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    service = EmbeddingService()

    errors = _run_concurrently(lambda _index: service.embed_query("giờ làm việc"))

    assert errors == []
    assert len(fake_model.loaded) == 1


def test_concurrent_queries_keep_the_cache_bounded_without_errors(fake_model, monkeypatch):
    monkeypatch.setattr(embeddings, "QUERY_CACHE_SIZE", 50)
    monkeypatch.setenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    service = EmbeddingService()
    switch_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # switch threads often, so racing evictions interleave
    try:
        errors = _run_concurrently(
            lambda index: [service.embed_query(f"câu hỏi {index}-{n}") for n in range(300)]
        )
    finally:
        sys.setswitchinterval(switch_interval)

    assert errors == []
    assert service.query_cache_info().currsize <= 50
