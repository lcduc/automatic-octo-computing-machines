"""
HTTP API of the model-server (internal Docker network only; no published port).

Every route except ``/health/live`` needs ``X-Service-Token: MODEL_SERVER_TOKEN``.
Chat-path calls (``/embed`` with ``kind=query``, ``/rerank``) run in the chat
lane; passage embedding and ``/ocr`` in the ingestion lane.
"""

# Standard library imports
import asyncio
import hmac
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

# Third-party imports
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

# Local imports
from .model_host import ModelHost
from .scheduler import Lane, PriorityScheduler

logger = logging.getLogger(__name__)

MAX_EMBED_TEXTS = 512
MAX_RERANK_TEXTS = 200
MAX_TEXT_CHARS = 20_000
#: Largest page image accepted by /ocr.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


class EmbedRequest(BaseModel):
    """Texts to embed."""

    texts: List[str] = Field(..., min_length=1, max_length=MAX_EMBED_TEXTS)
    kind: Literal["query", "passage"]


class EmbedResponse(BaseModel):
    """One vector per text."""

    model: str
    vectors: List[List[float]]


class RerankRequest(BaseModel):
    """Candidates to score against a query."""

    query: str = Field(..., max_length=MAX_TEXT_CHARS)
    texts: List[str] = Field(..., max_length=MAX_RERANK_TEXTS)


class RerankResponse(BaseModel):
    """Scores in [0, 1], or ``None`` without a reranker."""

    scores: Optional[List[float]]


class OcrResponse(BaseModel):
    """Recognised text of one page."""

    engine: str
    text: str


def create_model_server_app(host: ModelHost, scheduler: PriorityScheduler, token: str) -> FastAPI:
    """
    Build the app.

    Args:
        host: The (not yet loaded) models.
        scheduler: Chat/ingestion lanes.
        token: Required ``X-Service-Token``; an empty token refuses every call.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await asyncio.to_thread(host.load)
        yield

    app = FastAPI(title="Model server", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def authorized(x_service_token: str = Header("", alias="X-Service-Token")) -> None:
        if not token or not hmac.compare_digest(x_service_token.encode(), token.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid service token")

    @app.get("/health/live")
    async def live() -> dict:
        """200 once the models are loaded (the container healthcheck)."""
        if not host.loaded:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Models are loading")
        return {"status": "ok"}

    @app.get("/ready", dependencies=[Depends(authorized)])
    async def ready() -> dict:
        """Loaded models, free VRAM and current load."""
        return {"status": "ok" if host.loaded else "loading", "models": host.describe(),
                "gpu": host.gpu_memory(), "load": scheduler.stats()}

    @app.post("/embed", response_model=EmbedResponse, dependencies=[Depends(authorized)])
    async def embed(body: EmbedRequest) -> EmbedResponse:
        """Embed queries (chat lane) or passages (ingestion lane)."""
        texts = [text[:MAX_TEXT_CHARS] for text in body.texts]
        query = body.kind == "query"
        vectors = await scheduler.run(Lane.CHAT if query else Lane.INGESTION, host.embed, texts, query)
        return EmbedResponse(model=host.embedding.model_name, vectors=vectors)

    @app.post("/rerank", response_model=RerankResponse, dependencies=[Depends(authorized)])
    async def rerank(body: RerankRequest) -> RerankResponse:
        """Cross-encoder scores (chat lane)."""
        texts = [text[:MAX_TEXT_CHARS] for text in body.texts]
        return RerankResponse(scores=await scheduler.run(Lane.CHAT, host.rerank, body.query, texts))

    @app.post("/ocr", response_model=OcrResponse, dependencies=[Depends(authorized)])
    async def ocr(request: Request) -> OcrResponse:
        """Recognise one page image sent as the raw request body (ingestion lane)."""
        if host.ocr is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OCR is disabled (DOCLING_OCR_ENABLED)")
        image = await request.body()
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Page image missing or too large")
        descriptor, path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(image)
            text = await scheduler.run(Lane.INGESTION, host.ocr.extract_text, path)
        finally:
            os.unlink(path)
        return OcrResponse(engine=host.ocr.name, text=text or "")

    return app
