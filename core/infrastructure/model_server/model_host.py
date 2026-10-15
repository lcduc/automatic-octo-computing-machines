"""
Loads the GPU models once and keeps them resident for the model-server (RES-01).
"""

# Standard library imports
import logging
import os
from typing import Any, Dict, List, Optional

# Local imports
from config.model_server_settings import ModelServerConfig
from config.settings import Config
from core.document_processing.ocr_base import OCREngine
from core.retrieval.embeddings import EmbeddingService

logger = logging.getLogger(__name__)

MIB = 1024 * 1024


class ModelHost:
    """The embedding model, the reranker and the OCR engine of this box."""

    def __init__(self):
        self.embedding: Optional[EmbeddingService] = None
        self.reranker = None
        self.ocr: Optional[OCREngine] = None

    @staticmethod
    def apply_gpu_limits() -> None:
        """
        Cap GPU memory per framework so the models cannot starve a neighbour (the router SLM).

        Paddle reads ``FLAGS_gpu_memory_limit_mb`` when it is first imported, so this
        must run before any model loads. Torch's cap is a fraction of GPU 0.
        """
        ocr_limit_mb = ModelServerConfig.MODEL_SERVER_OCR_GPU_MEMORY_MB()
        if ocr_limit_mb:
            os.environ.setdefault("FLAGS_gpu_memory_limit_mb", str(ocr_limit_mb))
        fraction = ModelServerConfig.MODEL_SERVER_TORCH_GPU_FRACTION()
        try:
            import torch

            if fraction and torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(fraction, 0)
                logger.info("GPU caps: torch %.0f%% of GPU 0, paddle %s MiB", fraction * 100, ocr_limit_mb or "unlimited")
        except Exception:
            logger.exception("Cannot cap torch GPU memory")

    def load(self) -> None:
        """Load every enabled model (blocking; minutes on first boot without baked weights)."""
        from core.retrieval.embeddings import get_embedding_service

        self.apply_gpu_limits()

        self.embedding = get_embedding_service()
        self.embedding.get_embedder()
        self.embedding.load_query_adapter(Config.RAG.QUERY_ADAPTER_PATH())
        if Config.RAG.RERANKING_ENABLED():
            from core.retrieval.reranker import get_reranker

            reranker = get_reranker()
            self.reranker = reranker if reranker.available() else None
        if Config.OCR.DOCLING_OCR_ENABLED():
            from core.document_processing.engine_selector import get_local_engine

            self.ocr = get_local_engine()
        logger.info("Models resident: embedding=%s reranker=%s ocr=%s",
                    self.embedding.model_name, self.reranker is not None, self.ocr.name if self.ocr else None)

    @property
    def loaded(self) -> bool:
        """True once the embedding model (the one every request needs) is loaded."""
        return self.embedding is not None

    def embed(self, texts: List[str], query: bool) -> List[List[float]]:
        """Embed queries (with the query adapter) or passages; vectors are L2-normalized."""
        if query:
            return [self.embedding.embed_query(text).tolist() for text in texts]
        return self.embedding.embed_passages(texts).tolist()

    def rerank(self, query: str, texts: List[str]) -> Optional[List[float]]:
        """Cross-encoder scores, or ``None`` without a reranker."""
        return self.reranker.score(query, texts) if self.reranker is not None else None

    def gpu_memory(self) -> Optional[Dict[str, int]]:
        """Free and total VRAM of GPU 0 in MiB, or ``None`` without CUDA."""
        try:
            import torch

            if not torch.cuda.is_available():
                return None
            free, total = torch.cuda.mem_get_info(0)
            return {"free_mb": free // MIB, "total_mb": total // MIB}
        except Exception:
            logger.exception("Cannot read GPU memory")
            return None

    def describe(self) -> Dict[str, Any]:
        """What is loaded, for ``/ready``."""
        return {
            "embedding": self.embedding.model_name if self.embedding else None,
            "reranker": self.reranker is not None,
            "ocr": self.ocr.name if self.ocr else None,
        }
