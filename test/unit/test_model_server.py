"""
The model-server end to end without GPU models: the real app and client with a
fake model host, the remote embedding/reranker/OCR adapters, and the two-lane scheduler.
"""

import asyncio
import threading

import httpx
import numpy as np
import pytest
from starlette.testclient import TestClient

from core.document_processing.remote_ocr_engine import RemoteOCREngine
from core.infrastructure.model_server.app import create_model_server_app
from core.infrastructure.model_server.scheduler import Lane, PriorityScheduler
from core.infrastructure.model_server_client import ModelServerClient, ModelServerError
from core.retrieval.remote_models import RemoteEmbeddingService, RemoteReranker

TOKEN = "m" * 48


class FakeEmbedding:
    model_name = "paraphrase-multilingual-MiniLM-L12-v2"


class FakeOcr:
    name = "paddleocr-vl"

    def extract_text(self, path):
        with open(path, "rb") as handle:
            return f"page of {len(handle.read())} bytes"


class FakeHost:
    """Stands in for ModelHost: deterministic vectors, scores and OCR."""

    def __init__(self):
        self.embedding = None
        self.reranker = True
        self.ocr = FakeOcr()
        self.calls = []

    def load(self):
        self.embedding = FakeEmbedding()

    @property
    def loaded(self):
        return self.embedding is not None

    def embed(self, texts, query):
        self.calls.append(("query" if query else "passage", len(texts)))
        return [[1.0, 0.0] if query else [0.0, 1.0] for _ in texts]

    def rerank(self, query, texts):
        return [round(1.0 / (index + 1), 3) for index, _ in enumerate(texts)]

    def gpu_memory(self):
        return {"free_mb": 9000, "total_mb": 12288}

    def describe(self):
        return {"embedding": self.embedding.model_name, "reranker": True, "ocr": self.ocr.name}


@pytest.fixture
def server():
    host = FakeHost()
    app = create_model_server_app(host, PriorityScheduler(slots=3, ingestion_limit=1), TOKEN)
    with TestClient(app) as test_client:
        test_client.host = host
        yield test_client


def _client_for(test_client, token=TOKEN):
    """A ModelServerClient whose network is the in-process app."""

    def forward(request: httpx.Request) -> httpx.Response:
        response = test_client.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)

    return ModelServerClient("http://model-server:8600", token, 5, 5, transport=httpx.MockTransport(forward))


def test_every_call_but_liveness_needs_the_service_token(server):
    assert server.get("/health/live").status_code == 200
    assert server.get("/ready").status_code == 401
    assert server.post("/embed", json={"texts": ["x"], "kind": "query"}, headers={"X-Service-Token": "wrong"}).status_code == 401
    with pytest.raises(ModelServerError, match="401"):
        _client_for(server, token="wrong").ready()


def test_remote_adapters_match_the_in_process_interfaces(server, tmp_path):
    client = _client_for(server)
    embedding = RemoteEmbeddingService(client)
    embedding.get_embedder()  # the served model matches EMBEDDING_MODEL
    assert embedding.embed_query("giờ làm việc").tolist() == [1.0, 0.0]
    passages = embedding.embed_passages([f"chunk {i}" for i in range(300)], batch_size=128)
    assert passages.shape == (300, 2) and passages.dtype == np.float32
    assert server.host.calls == [("query", 1), ("passage", 128), ("passage", 128), ("passage", 44)]

    assert RemoteReranker(client, available=True).score("q", ["a", "b"]) == [1.0, 0.5]
    assert RemoteReranker(client, available=False).score("q", ["a"]) is None

    page = tmp_path / "page.png"
    page.write_bytes(b"\x89PNG fake page")
    engine = RemoteOCREngine(client)
    assert engine.extract_text(str(page)) == "page of 14 bytes"
    assert engine.name == "model-server:paddleocr-vl"

    ready = client.ready()
    assert ready["status"] == "ok" and ready["gpu"]["free_mb"] == 9000


def test_a_mismatched_embedding_model_is_refused_at_start_up(server, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    with pytest.raises(ModelServerError, match="bge-m3"):
        RemoteEmbeddingService(_client_for(server)).get_embedder()


@pytest.mark.asyncio
async def test_chat_work_overtakes_queued_ingestion_and_ingestion_runs_one_at_a_time():
    scheduler = PriorityScheduler(slots=2, ingestion_limit=1)
    order, release = [], threading.Event()

    def job(name, block=False):
        order.append(name)
        if block:
            release.wait(5)
        return name

    first_page = asyncio.create_task(scheduler.run(Lane.INGESTION, job, "ocr-1", True))
    await asyncio.sleep(0.05)
    second_page = asyncio.create_task(scheduler.run(Lane.INGESTION, job, "ocr-2"))
    await asyncio.sleep(0.05)
    assert scheduler.stats()["ingestion_running"] == 1 and order == ["ocr-1"]  # OCR concurrency = 1

    chat = asyncio.create_task(scheduler.run(Lane.CHAT, job, "query"))
    assert await asyncio.wait_for(chat, 2) == "query"  # a slot is always free for chat
    release.set()
    await asyncio.gather(first_page, second_page)
    assert order == ["ocr-1", "query", "ocr-2"]
    with pytest.raises(ValueError):
        PriorityScheduler(slots=2, ingestion_limit=2)
