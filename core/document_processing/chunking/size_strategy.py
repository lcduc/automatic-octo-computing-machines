"""
Size-based chunking: whole sentences packed up to a character budget.
"""

# Standard library imports
from typing import Any, Dict, List, Optional

# Local imports
from models.knowledge import ChunkDraft
from utils.text_utils import TextUtils


class SizeChunker:
    """Packs sentences into chunks of at most ``max_chars`` (``##`` headings also start a new chunk)."""

    def __init__(self, max_chars: int, overlap: bool = False):
        """
        Args:
            max_chars: Target maximum characters per chunk.
            overlap: Repeat the last sentence of a chunk at the start of the next one.
        """
        self._max_chars = max_chars
        self._overlap = overlap

    def split(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[ChunkDraft]:
        """
        Split ``text``; every chunk gets a copy of ``metadata``.

        Returns:
            Non-empty chunks in order.
        """
        # TextUtils.chunk_text carries one sentence over whenever overlap > 0.
        pieces = TextUtils.chunk_text(text, chunk_size=self._max_chars, overlap=1 if self._overlap else 0)
        cleaned = (TextUtils.clean_chunk_text(piece) for piece in pieces)
        return [ChunkDraft(content, dict(metadata or {})) for content in cleaned if content.strip()]
