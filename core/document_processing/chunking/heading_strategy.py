"""
Heading-based chunking for markdown: one chunk per section, optionally size-capped.
"""

# Standard library imports
import re
from typing import List, Optional, Tuple

# Local imports
from models.knowledge import ChunkDraft
from utils.text_utils import TextUtils
from .size_strategy import SizeChunker

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)")
#: Longest heading text copied into chunk metadata.
MAX_HEADING_METADATA_CHARS = 200


class HeadingChunker:
    """Starts a chunk at every markdown heading up to ``max_level``; long sections are size-split."""

    def __init__(self, max_level: int = 2, max_chars: Optional[int] = 3000):
        """
        Args:
            max_level: Deepest heading level (1-6) that starts a new chunk.
            max_chars: Size cap per chunk; ``None`` keeps each section whole.
        """
        self._max_level = max_level
        self._max_chars = max_chars

    def split(self, text: str) -> List[ChunkDraft]:
        """
        Split markdown ``text`` into sections.

        Returns:
            Chunks in order; each carries its ``heading`` (when it has one). Text
            with no headings becomes one section.
        """
        drafts: List[ChunkDraft] = []
        for heading, body in self._sections(text):
            metadata = {"heading": heading[:MAX_HEADING_METADATA_CHARS]} if heading else {}
            content = TextUtils.clean_chunk_text(body)
            if not content.strip():
                continue
            if self._max_chars is not None and len(content) > self._max_chars:
                drafts.extend(SizeChunker(self._max_chars).split(content, metadata))
            else:
                drafts.append(ChunkDraft(content, metadata))
        return drafts

    def _sections(self, text: str) -> List[Tuple[Optional[str], str]]:
        """``(heading text or None, section text including its heading line)`` pairs."""
        sections: List[Tuple[Optional[str], str]] = []
        heading: Optional[str] = None
        lines: List[str] = []
        for line in text.splitlines():
            match = HEADING_PATTERN.match(line)
            if match and len(match.group(1)) <= self._max_level:
                if lines:
                    sections.append((heading, "\n".join(lines)))
                heading, lines = match.group(2).strip(), [line]
            else:
                lines.append(line)
        if lines:
            sections.append((heading, "\n".join(lines)))
        return sections
