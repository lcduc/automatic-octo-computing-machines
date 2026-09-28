"""
Whole-document chunking: the entire text as a single chunk (short FAQ entries, notices).
"""

# Standard library imports
from typing import List

# Local imports
from models.knowledge import ChunkDraft
from utils.text_utils import TextUtils
from .errors import MAX_CHUNK_CHARS, InvalidChunkingError


class WholeChunker:
    """Keeps the text together as one chunk."""

    def split(self, text: str) -> List[ChunkDraft]:
        """
        Returns:
            One chunk, or none for blank text.

        Raises:
            InvalidChunkingError: The text is longer than ``MAX_CHUNK_CHARS``.
        """
        content = TextUtils.clean_chunk_text(text).strip()
        if len(content) > MAX_CHUNK_CHARS:
            raise InvalidChunkingError(
                f"The text has {len(content)} characters; one chunk holds at most {MAX_CHUNK_CHARS}. Choose another strategy."
            )
        return [ChunkDraft(content)] if content else []
