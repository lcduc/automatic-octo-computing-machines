"""
Question/answer chunking for FAQs: one chunk per pair.
"""

# Standard library imports
import re
import unicodedata
from typing import List, Optional, Tuple

# Local imports
from models.knowledge import ChunkDraft
from utils.text_utils import TextUtils
from .errors import InvalidChunkingError
from .markdown_tables import is_empty_row, is_separator_row, table_cells

#: Line prefixes on the accent-folded, lower-cased line, e.g. "Câu hỏi 3:", "**Q:**", "Đáp:".
#: A bare "q"/"a" needs a colon so lettered list items ("a. ...") are not taken as answers.
QUESTION_PREFIX = re.compile(r"^[\s>*_\-]*(?:q\s*\d*\s*:|(?:question|hoi|cau hoi)\s*\d*\s*[:.])\**\s*")
ANSWER_PREFIX = re.compile(r"^[\s>*_\-]*(?:a\s*\d*\s*:|(?:answer|dap|dap an|tra loi)\s*\d*\s*[:.])\**\s*")
#: Header words identifying the question / answer columns of a table.
QUESTION_HEADERS = ("cau hoi", "question", "hoi")
ANSWER_HEADERS = ("tra loi", "answer", "dap")
#: Longest question text copied into chunk metadata.
MAX_QUESTION_METADATA_CHARS = 300
NO_PAIRS_ERROR = (
    "No question/answer pairs found. Expected 'Hỏi:'/'Đáp:' (or 'Q:'/'A:') lines, "
    "or a table with question and answer columns."
)


class QaPairChunker:
    """Finds Q&A pairs in prefixed lines or in a two-column table; each pair is one chunk."""

    def split(self, text: str) -> List[ChunkDraft]:
        """
        Extract the pairs of ``text``.

        Raises:
            InvalidChunkingError: No pair was found.
        """
        # NFC keeps accent folding one character per character, so match offsets fit the original line.
        text = unicodedata.normalize("NFC", text)
        pairs = self._table_pairs(text) + self._line_pairs(text)
        if not pairs:
            raise InvalidChunkingError(NO_PAIRS_ERROR)
        return [
            ChunkDraft(f"Hỏi: {question}\nĐáp: {answer}", {"question": question[:MAX_QUESTION_METADATA_CHARS]})
            for question, answer in pairs
        ]

    @staticmethod
    def _fold(line: str) -> str:
        """Lower-cased line without Vietnamese accents, for prefix matching."""
        return TextUtils.strip_vietnamese_accents(line.lower())

    def _line_pairs(self, text: str) -> List[Tuple[str, str]]:
        """Pairs written as a question line followed by an answer line (both may continue over lines)."""
        pairs: List[Tuple[str, str]] = []
        question: List[str] = []
        answer: List[str] = []
        in_answer = False

        def flush() -> None:
            if question and answer:
                pairs.append((" ".join(question).strip(), "\n".join(answer).strip()))

        for line in text.splitlines():
            if not line.strip() or table_cells(line) is not None:
                continue
            folded = self._fold(line)
            question_match = QUESTION_PREFIX.match(folded)
            answer_match = ANSWER_PREFIX.match(folded)
            if question_match:
                flush()
                # On NFC text folding keeps the length, so the match end indexes the original line.
                question, answer, in_answer = [line[question_match.end():].strip()], [], False
            elif answer_match and question:
                answer, in_answer = [line[answer_match.end():].strip()], True
            elif in_answer:
                answer.append(line.strip())
            elif question:
                question.append(line.strip())
        flush()
        return pairs

    def _table_pairs(self, text: str) -> List[Tuple[str, str]]:
        """Pairs from table rows whose header has a question and an answer column."""
        pairs: List[Tuple[str, str]] = []
        columns: Optional[Tuple[int, int]] = None
        for line in text.splitlines():
            cells = table_cells(line)
            if cells is None:
                columns = None
                continue
            if is_separator_row(line) or is_empty_row(cells):
                continue
            if columns is None:
                columns = self._qa_columns(cells)
                continue
            question_index, answer_index = columns
            if question_index == -1 or max(columns) >= len(cells):
                continue
            question, answer = cells[question_index], cells[answer_index]
            if not is_empty_row([question]) and not is_empty_row([answer]):
                pairs.append((question, answer))
        return pairs

    def _qa_columns(self, header: List[str]) -> Tuple[int, int]:
        """Indexes of the question and answer columns, or ``(-1, -1)`` when the table has neither."""
        folded = [self._fold(cell) for cell in header]
        question_index = next((i for i, cell in enumerate(folded) if any(word in cell for word in QUESTION_HEADERS)), -1)
        answer_index = next(
            (i for i, cell in enumerate(folded) if i != question_index and any(word in cell for word in ANSWER_HEADERS)),
            -1,
        )
        if question_index == -1 or answer_index == -1:
            return -1, -1
        return question_index, answer_index
