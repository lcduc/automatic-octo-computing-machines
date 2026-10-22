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

from api.schemas.admin import ModelServerLoad
from config.settings import Config
from core.document_processing.remote_ocr_engine import RemoteOCREngine
from core.infrastructure.model_server.app import create_model_server_app
from core.infrastructure.model_server.scheduler import Lane, PriorityScheduler, SchedulerBusyError
from core.infrastructure.model_server_client import ModelServerClient, ModelServerError
from core.retrieval.remote_models import RemoteEmbeddingService, RemoteReranker
from services.readiness_service import ReadinessService

TOKEN = "m" * 48


def _scheduler(slots=2, max_waiting=8, chat_wait=5.0, ingestion_wait=5.0):
    """A scheduler with one ingestion slot and test-sized waits."""
    return PriorityScheduler(slots, 1, max_waiting, chat_wait, ingestion_wait)


class FakeEmbedding:
    model_name = Config.LLM.EMBEDDING_MODEL()


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
    app = create_model_server_app(host, _scheduler(slots=3), TOKEN)
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


@pytest.mark.asyncio
async def test_admin_status_reports_model_server_queues_and_vram_or_none_when_unreachable(server):
    status = await ReadinessService(database=None, model_server=_client_for(server)).model_server_status()
    load = ModelServerLoad.from_ready(status)
    assert (load.chat_waiting, load.ingestion_waiting, load.gpu_free_mb, load.gpu_total_mb) == (0, 0, 9000, 12288)

    unreachable = ReadinessService(database=None, model_server=_client_for(server, token="wrong"))
    assert ModelServerLoad.from_ready(await unreachable.model_server_status()) is None
    assert ModelServerLoad.from_ready(await ReadinessService(database=None).model_server_status()) is None


def test_a_mismatched_embedding_model_is_refused_at_start_up(server, monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    with pytest.raises(ModelServerError, match="bge-m3"):
        RemoteEmbeddingService(_client_for(server)).get_embedder()


@pytest.mark.asyncio
async def test_chat_work_overtakes_queued_ingestion_and_ingestion_runs_one_at_a_time():
    scheduler = _scheduler()
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
        PriorityScheduler(2, 2, 8, 5.0, 5.0)


@pytest.mark.asyncio
async def test_a_full_queue_and_a_slow_wait_are_refused_instead_of_piling_up():
    scheduler = _scheduler(slots=2, max_waiting=1, chat_wait=0.1)
    release = threading.Event()

    def block():
        release.wait(5)

    running = [asyncio.create_task(scheduler.run(Lane.CHAT, block)) for _ in range(2)]  # both slots busy
    await asyncio.sleep(0.05)
    queued = asyncio.create_task(scheduler.run(Lane.CHAT, block))
    await asyncio.sleep(0.02)
    with pytest.raises(SchedulerBusyError, match="queue is full"):
        await scheduler.run(Lane.CHAT, block)
    with pytest.raises(SchedulerBusyError, match="within"):
        await queued  # waited chat_wait seconds without a slot
    assert scheduler.stats()["chat_waiting"] == 0

    release.set()
    await asyncio.gather(*running)
    assert await scheduler.run(Lane.CHAT, lambda: "ok") == "ok"  # recovered, nothing leaked


@pytest.mark.asyncio
async def test_a_chat_call_that_gives_up_frees_the_ingestion_it_was_holding_back():
    scheduler = _scheduler(slots=2, chat_wait=0.1)
    release = threading.Event()
    blockers = [asyncio.create_task(scheduler.run(Lane.CHAT, release.wait, 5)) for _ in range(2)]
    await asyncio.sleep(0.05)
    ingestion = asyncio.create_task(scheduler.run(Lane.INGESTION, lambda: "page"))
    with pytest.raises(SchedulerBusyError):
        await scheduler.run(Lane.CHAT, lambda: None)  # chat waiter blocks ingestion, then times out
    release.set()
    await asyncio.gather(*blockers)
    assert await asyncio.wait_for(ingestion, 2) == "page"


def test_the_model_server_answers_503_with_retry_after_when_busy():
    class BusyScheduler:
        async def run(self, lane, function, *args):
            raise SchedulerBusyError("chat queue is full")

    host = FakeHost()
    with TestClient(create_model_server_app(host, BusyScheduler(), TOKEN)) as busy:
        response = busy.post("/rerank", json={"query": "q", "texts": ["a"]}, headers={"X-Service-Token": TOKEN})
    assert response.status_code == 503 and response.headers["Retry-After"] == "5"
