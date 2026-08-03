"""
OCR engine abstraction.

Three interchangeable engines implement :class:`OCREngine` — two local
(CPU/GPU, auto-selected by :mod:`engine_selector`) and one online (Datalab's
hosted Surya OCR) — so the document processor doesn't need to know which one
is active.
"""

from abc import ABC, abstractmethod


class OCREngine(ABC):
    """Extracts text from a single rendered page image."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in logs and document metadata."""
        raise NotImplementedError

    @abstractmethod
    def extract_text(self, image_path: str) -> str:
        """
        Run OCR on the image at ``image_path`` and return the extracted text.

        This is a blocking call — callers on the event loop must run it via
        ``asyncio.to_thread`` rather than awaiting it directly.

        Args:
            image_path: Path to a PNG/JPEG page render.

        Returns:
            Extracted text, or an empty string if nothing was recognized or
            the engine failed (engines log their own failures; callers should
            treat an empty string as "no text found", not as an error to raise).
        """
        raise NotImplementedError
