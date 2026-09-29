"""
Chunking entry point: builds the strategy named by a ``ChunkingSpec`` and checks its output.
"""

# Standard library imports
import logging
from collections import Counter
from typing import Dict, List, Optional

# Local imports
from config.settings import Config
from models.knowledge import AUTO_STRATEGY, EXTRACTION_DOCLING, ChunkDraft, ChunkingResult, ChunkingSpec
from .errors import InvalidChunkingError
from .heading_strategy import HeadingChunker
from .legal_article_strategy import LEVELS, LegalArticleChunker
from .qa_pair_strategy import QaPairChunker
from .size_strategy import SizeChunker
from .table_rows_strategy import TableRowsChunker
from .whole_strategy import WholeChunker

logger = logging.getLogger(__name__)

STRATEGIES = {
    "size": SizeChunker,
    "heading": HeadingChunker,
    "legal_article": LegalArticleChunker,
    "qa_pair": QaPairChunker,
    "table_rows": TableRowsChunker,
    "whole": WholeChunker,
}
#: What each strategy does, for the admin UI.
STRATEGY_DESCRIPTIONS = {
    AUTO_STRATEGY: "Each file type's built-in splitting (Docling: by heading; OCR and plain text: by size).",
    "size": "Whole sentences packed up to a character limit.",
    "heading": "One chunk per markdown heading section; long sections are split by size.",
    "legal_article": "Vietnamese legal texts: one chunk per Điều (or Chương / Mục / Khoản), labelled for citation.",
    "qa_pair": "FAQs: one chunk per question and answer ('Hỏi:'/'Đáp:' lines or a question/answer table).",
    "table_rows": "Tables: groups of rows, each repeating the header row.",
    "whole": "The entire text as one chunk (short entries only).",
}
#: Metadata key a structural strategy sets when it found the structure it looks for.
STRUCTURE_KEYS = {"heading": ("heading", "markdown headings"), "legal_article": ("article", "Điều markers")}
#: Joins the parts of a section label ("Chương I · Điều 12").
SECTION_SEPARATOR = " · "
#: Extraction paths whose ``auto`` splitting is by heading (the others split by size).
HEADING_EXTRACTIONS = {EXTRACTION_DOCLING}
#: Chunks shorter than this are flagged in previews.
MIN_USEFUL_CHUNK_CHARS = 50
#: Chunks longer than this multiple of the strategy's limit are flagged in previews.
OVERSIZE_FACTOR = 1.5


def section_label(metadata: Dict[str, object]) -> Optional[str]:
    """
    Where a chunk sits in its document, for citations (GEN-03).

    Legal chunks give their Chương/Mục/Điều/Khoản labels outermost first;
    heading chunks give their heading; other chunks have no section.
    """
    legal = [str(metadata[level]) for level in LEVELS if metadata.get(level)]
    if legal:
        return SECTION_SEPARATOR.join(legal)
    heading = metadata.get("heading")
    return str(heading) if heading else None


class Chunker:
    """Splits text with a named strategy and reports anything an admin should look at."""

    def split(self, text: str, spec: ChunkingSpec, extraction_method: Optional[str]) -> ChunkingResult:
        """
        Chunk ``text`` according to ``spec``.

        Args:
            extraction_method: How the text was extracted (``docling``, ``ocr``,
                ``local``, ``text``); decides what ``auto`` means.

        Raises:
            InvalidChunkingError: Unknown strategy or parameters, no text, or the
                strategy found nothing it can chunk.
        """
        logger.debug("Chunking %d characters with %s %s", len(text), spec.strategy, spec.params)
        drafts = self._build(spec, extraction_method).split(text)
        if not drafts:
            raise InvalidChunkingError("The document has no text to chunk")
        return ChunkingResult(drafts=drafts, warnings=self._warnings(drafts, spec))

    @staticmethod
    def _build(spec: ChunkingSpec, extraction_method: Optional[str]):
        """The strategy object for ``spec``."""
        if spec.strategy == AUTO_STRATEGY:
            if extraction_method in HEADING_EXTRACTIONS:
                return HeadingChunker(max_level=6, max_chars=None)
            return SizeChunker(Config.File.CHUNK_SIZE(), overlap=Config.File.CHUNK_OVERLAP() > 0)
        strategy_class = STRATEGIES.get(spec.strategy)
        if strategy_class is None:
            raise InvalidChunkingError(f"Unknown chunking strategy '{spec.strategy}'")
        try:
            return strategy_class(**spec.params)
        except (TypeError, ValueError) as exc:
            raise InvalidChunkingError(f"Invalid parameters for '{spec.strategy}': {exc}") from exc

    @staticmethod
    def _warnings(drafts: List[ChunkDraft], spec: ChunkingSpec) -> List[str]:
        """Human-readable problems with the result (it is still usable)."""
        warnings: List[str] = []
        structure = STRUCTURE_KEYS.get(spec.strategy)
        if structure and not any(structure[0] in draft.metadata for draft in drafts):
            warnings.append(f"No {structure[1]} found; the text was split by size instead.")
        short = sum(1 for draft in drafts if len(draft.content) < MIN_USEFUL_CHUNK_CHARS)
        if short:
            warnings.append(f"{short} chunk(s) are shorter than {MIN_USEFUL_CHUNK_CHARS} characters.")
        limit: Optional[int] = spec.params.get("max_chars")
        if spec.strategy == "size" and limit is None:
            limit = Config.File.CHUNK_SIZE()
        if limit:
            long = sum(1 for draft in drafts if len(draft.content) > limit * OVERSIZE_FACTOR)
            if long:
                warnings.append(f"{long} chunk(s) are much longer than {limit} characters (no sentence break to split at).")
        duplicates: Dict[str, int] = {c: n for c, n in Counter(d.content for d in drafts).items() if n > 1}
        if duplicates:
            warnings.append(f"{sum(duplicates.values()) - len(duplicates)} chunk(s) repeat another chunk's text.")
        return warnings
