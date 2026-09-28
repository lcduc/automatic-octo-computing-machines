"""
Legal-structure chunking for Vietnamese legal texts: Chương / Mục / Điều / Khoản.

Each chunk is one unit at the chosen level (by default one Điều) and carries its
position in the text as metadata, so answers can cite "Điều 12" precisely.
"""

# Standard library imports
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Local imports
from models.knowledge import ChunkDraft
from utils.text_utils import TextUtils
from .size_strategy import SizeChunker

#: Structural levels from the outermost; ``split_at`` picks one.
LEVELS = ("chapter", "section", "article", "clause")
#: Patterns on the accent-folded, lower-cased line (after markdown decoration is stripped).
LEVEL_PATTERNS = {
    "chapter": re.compile(r"^chuong\s+([ivxlcdm]+|\d+)\b"),
    "section": re.compile(r"^muc\s+(\d+)\b"),
    "article": re.compile(r"^dieu\s+(\d+[a-z]?)\b"),
    "clause": re.compile(r"^(\d+)\.\s"),
}
LEVEL_LABELS = {"chapter": "Chương", "section": "Mục", "article": "Điều", "clause": "Khoản"}
#: Leading markdown decoration Docling adds to headings (``#``, ``**``, ``>``, list bullets).
DECORATION_PATTERN = re.compile(r"^[\s#>*_\-]+")
#: A unit above ``split_at`` shorter than this (e.g. "Chương I / QUY ĐỊNH CHUNG") only titles what follows.
MIN_HEADER_UNIT_CHARS = 200
#: Longest title kept for a level in the breadcrumb.
MAX_TITLE_CHARS = 150
BREADCRUMB_SEPARATOR = " › "


@dataclass
class _Unit:
    """Consecutive lines belonging to one structural unit."""

    level: Optional[str]
    metadata: Dict[str, str]
    ancestors: List[str]
    lines: List[str] = field(default_factory=list)


class LegalArticleChunker:
    """Splits at Chương/Mục/Điều/Khoản markers; oversized units are size-split and keep their metadata."""

    def __init__(self, split_at: str = "article", max_chars: int = 3000, breadcrumb: bool = True):
        """
        Args:
            split_at: One of ``LEVELS``; that level and every level above it start a new chunk.
            max_chars: Size cap per chunk.
            breadcrumb: Prefix each chunk with its enclosing Chương/Mục titles.
        """
        self._split_depth = LEVELS.index(split_at)
        self._max_chars = max_chars
        self._breadcrumb = breadcrumb

    def split(self, text: str) -> List[ChunkDraft]:
        """
        Split ``text`` at legal-structure markers.

        Returns:
            Chunks in order, with ``chapter``/``section``/``article``/``clause``
            metadata where present. Text without any marker is size-split
            without structural metadata.
        """
        drafts: List[ChunkDraft] = []
        for unit in self._units(text):
            drafts.extend(self._unit_drafts(unit))
        return drafts

    def _level_of(self, line: str) -> Optional[Tuple[str, str]]:
        """``(level, number)`` if ``line`` opens a unit tracked at this depth, else ``None``."""
        folded = TextUtils.strip_vietnamese_accents(DECORATION_PATTERN.sub("", line).lower())
        for level in LEVELS[: self._split_depth + 1]:
            match = LEVEL_PATTERNS[level].match(folded)
            if match:
                return level, match.group(1).upper() if level == "chapter" else match.group(1)
        return None

    def _is_short_header(self, unit: _Unit) -> bool:
        """A unit above ``split_at`` holding little more than its title (e.g. "Chương I / QUY ĐỊNH CHUNG")."""
        is_above_split = unit.level is not None and LEVELS.index(unit.level) < self._split_depth
        return is_above_split and len("\n".join(unit.lines).strip()) < MIN_HEADER_UNIT_CHARS

    def _units(self, text: str) -> List[_Unit]:
        """
        Group lines into units, tracking the enclosing labels and titles.

        A short header unit is not emitted; its text becomes the title that the
        units inside it show in their breadcrumb.
        """
        labels: Dict[str, str] = {}
        titles: Dict[str, str] = {}
        units: List[_Unit] = []
        current = _Unit(level=None, metadata={}, ancestors=[])
        for line in text.splitlines():
            found = self._level_of(line) if line.strip() else None
            if found is None:
                current.lines.append(line)
                continue
            if self._is_short_header(current):
                parts = (DECORATION_PATTERN.sub("", part).strip(" *") for part in current.lines if part.strip())
                titles[current.level] = " ".join(parts)[:MAX_TITLE_CHARS]
            else:
                units.append(current)
            level, number = found
            depth = LEVELS.index(level)
            for deeper in LEVELS[depth:]:
                labels.pop(deeper, None)
                titles.pop(deeper, None)
            labels[level] = f"{LEVEL_LABELS[level]} {number}"
            titles[level] = DECORATION_PATTERN.sub("", line).strip(" *")[:MAX_TITLE_CHARS]
            ancestors = [titles[upper] for upper in LEVELS[:depth] if upper in titles]
            current = _Unit(level=level, metadata=dict(labels), ancestors=ancestors, lines=[line])
        units.append(current)
        return [unit for unit in units if "\n".join(unit.lines).strip()]

    def _unit_drafts(self, unit: _Unit) -> List[ChunkDraft]:
        """One unit as one or more chunks, each prefixed with its breadcrumb."""
        body = TextUtils.clean_chunk_text("\n".join(unit.lines))
        prefix = BREADCRUMB_SEPARATOR.join(unit.ancestors) if self._breadcrumb else ""
        if len(body) + len(prefix) <= self._max_chars:
            return [ChunkDraft(self._with_prefix(prefix, body), dict(unit.metadata))]
        # Pieces after the first lose the unit's own title line, so it joins the breadcrumb.
        unit_title = body.splitlines()[0].strip() if unit.level else ""
        piece_prefix = BREADCRUMB_SEPARATOR.join(filter(None, [prefix, unit_title])) if self._breadcrumb else ""
        # A long breadcrumb must not shrink the budget to nothing.
        budget = max(self._max_chars - len(piece_prefix), self._max_chars // 2)
        pieces = SizeChunker(budget).split(body, unit.metadata)
        return [
            ChunkDraft(self._with_prefix(prefix if index == 0 else piece_prefix, piece.content), piece.metadata)
            for index, piece in enumerate(pieces)
        ]

    @staticmethod
    def _with_prefix(prefix: str, body: str) -> str:
        """``body`` preceded by its breadcrumb line, if any."""
        return f"{prefix}\n{body}" if prefix else body
