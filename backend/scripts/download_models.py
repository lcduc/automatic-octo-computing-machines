"""
Pre-download the embedding, reranker, Docling PDF and OCR models into the local model cache.

Run once (locally, or as a Dockerfile build step) so the weights are baked in
and reviewable on disk under ``MODELS_DIR`` (default: ``model_weights/``)
instead of being fetched from Hugging Face on first request in production.

The OCR download is best-effort and only warms PP-OCRv6 (the CPU engine):
PaddleOCR-VL (the GPU engine) is left to download on first real GPU request,
since a Docker build step typically has no GPU attached to reliably warm it
against.

Usage:
    python -m scripts.download_models
"""

# Standard library imports
import logging
from pathlib import Path

# Local imports
from app.config.settings import Config
from app.core.document_processing.docling_processor import docling_models_dir
from app.core.retrieval.reranker import RERANKER_FALLBACK_MODEL

logger = logging.getLogger(__name__)


class ModelDownloader:
    """Fetches the configured embedding, reranker, Docling PDF and OCR models into ``MODELS_DIR``."""

    def __init__(self, models_dir: str = None):
        """
        Args:
            models_dir: Target cache directory; defaults to the configured
                ``MODELS_DIR``.
        """
        self._models_dir = models_dir or Config.Paths.MODELS_DIR()

    def download_embedding_model(self) -> str:
        """Download the configured sentence-transformers embedding model."""
        from sentence_transformers import SentenceTransformer

        model_name = Config.LLM.EMBEDDING_MODEL()
        logger.info("Downloading embedding model '%s' to %s", model_name, self._models_dir)
        SentenceTransformer(model_name, device="cpu", cache_folder=self._models_dir)
        return model_name

    def download_reranker_model(self, model_name: str) -> str:
        """Download one cross-encoder reranker model."""
        logger.info("Downloading reranker model '%s' to %s", model_name, self._models_dir)

        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        # Loaded directly via `transformers` (not CrossEncoder) for every
        # model — see core/retrieval/reranker.py for why.
        trust_remote_code = model_name.startswith("jinaai/")
        AutoTokenizer.from_pretrained(
            model_name, trust_remote_code=trust_remote_code, cache_dir=self._models_dir
        )
        AutoModelForSequenceClassification.from_pretrained(
            model_name,
            trust_remote_code=trust_remote_code,
            cache_dir=self._models_dir,
            low_cpu_mem_usage=False,
        )
        return model_name

    def download_docling_models(self) -> Path:
        """
        Download Docling's PDF models (layout, TableFormer) into :func:`docling_models_dir`.

        Not best-effort, unlike OCR: every PDF with a text layer goes through these models, and
        without them a box with no network silently parses PDFs as plain text (ING-13).
        Docling's own OCR, code/formula and picture models are off in this pipeline, so they are
        skipped.
        """
        from docling.utils.model_downloader import download_models

        target = docling_models_dir()
        logger.info("Downloading Docling PDF models (layout, TableFormer) to %s", target)
        download_models(
            output_dir=target,
            with_layout=True,
            with_tableformer=True,
            with_code_formula=False,
            with_picture_classifier=False,
            with_rapidocr=False,
        )
        return target

    def download_ocr_model(self) -> None:
        """
        Warm the PP-OCRv6 (CPU) OCR pipeline so its weights are cached.

        Best-effort: OCR is an optional feature (``DOCLING_OCR_ENABLED``), so a
        failure here (e.g. paddleocr not installed in some other invocation
        context) must not fail the whole download run.
        """
        try:
            from paddleocr import PaddleOCR

            logger.info("Warming PP-OCRv6 pipeline to cache its weights")
            PaddleOCR(
                device="cpu",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception:
            logger.exception("PP-OCRv6 warm-up failed; it will download on first use instead")

    def download_all(self) -> None:
        """Download every model the running configuration needs."""
        embedding_model = self.download_embedding_model()
        reranker_model = self.download_reranker_model(Config.RAG.RERANKER_MODEL())
        # Baked in too: the fallback is needed exactly when the network or the primary fails.
        fallback_model = self.download_reranker_model(RERANKER_FALLBACK_MODEL)
        docling_dir = self.download_docling_models()
        self.download_ocr_model()
        logger.info(
            "Model download complete: embedding=%s reranker=%s (fallback %s) docling=%s dir=%s",
            embedding_model,
            reranker_model,
            fallback_model,
            docling_dir,
            self._models_dir,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    ModelDownloader().download_all()
