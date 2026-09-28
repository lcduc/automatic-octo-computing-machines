"""
Local text extractors, the fallback when Docling declines or fails on a file.

Each extractor parses its file once and returns both the chunks the fallback
path has always produced and the full extracted text, which is stored so the
document can be re-chunked later without parsing it again.
"""

from abc import ABC, abstractmethod
from typing import List, NamedTuple, Optional, Sequence, Tuple
import io
import logging
import pypdf
from docx import Document
import pandas as pd
from openpyxl import load_workbook

logger = logging.getLogger(__name__)

#: Chunk size and overlap the fallback extractors have always used.
FALLBACK_CHUNK_SIZE = 1000
FALLBACK_OVERLAP = 200


class Extraction(NamedTuple):
    """What an extractor read from one file."""

    chunks: List[str]
    #: The whole text before chunking ("" when nothing was readable).
    text: str


class BaseFileExtractor(ABC):
    @abstractmethod
    async def extract(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        """Parse ``content`` into chunks plus its full text."""


class _NarrativeExtractor(BaseFileExtractor):
    """Extractors whose text is chunked by sentences; subclasses only read the text."""

    @abstractmethod
    def _read_text(self, content: bytes) -> str:
        """The file's full text."""

    async def extract(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        try:
            text = self._read_text(content)
        except Exception:
            logger.exception("%s failed for %s", type(self).__name__, filename)
            return Extraction([], "")
        return Extraction(smart_chunk_text(text, FALLBACK_CHUNK_SIZE, FALLBACK_OVERLAP), text)


class TXTTextExtractor(_NarrativeExtractor):
    def _read_text(self, content: bytes) -> str:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except UnicodeDecodeError:
                text = content.decode("utf-8", errors="ignore")
        return text.replace("\r\n", "\n").replace("\r", "\n")


class PDFTextExtractor(_NarrativeExtractor):
    def _read_text(self, content: bytes) -> str:
        pdf_reader = pypdf.PdfReader(io.BytesIO(content))
        text_parts = []
        for page_num, page in enumerate(pdf_reader.pages):
            try:
                page_text = page.extract_text()
            except Exception:
                logger.exception("Could not read the text of PDF page %d", page_num + 1)
                continue
            if page_text and page_text.strip():
                page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
                text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
        return "\n".join(text_parts)


def extract_tables_from_docx(doc):
    tables = []
    for table in doc.tables:
        rows = []
        for i, row in enumerate(table.rows):
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(cells)
        if rows:
            # Format as markdown table if possible
            header = rows[0]
            table_md = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            for row in rows[1:]:
                table_md.append("| " + " | ".join(row) + " |")
            tables.append("\n".join(table_md))
    return tables


class DOCXTextExtractor(_NarrativeExtractor):
    def _read_text(self, content: bytes) -> str:
        doc = Document(io.BytesIO(content))
        text_parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        table_texts = extract_tables_from_docx(doc)
        # Separate narrative and tables with clear markers
        all_parts = []
        if text_parts:
            all_parts.append("\n\n".join(text_parts))
        for i, table in enumerate(table_texts):
            all_parts.append(f"\n[Table {i+1}]\n{table}")
        return "\n\n".join(all_parts)


def smart_chunk_rows(rows, chunk_size=1000, header=None):
    """
    Chunk a list of rows (strings) into groups, ensuring no row is split across chunks.
    Each chunk is a string of joined rows, up to chunk_size characters.
    Optionally, prepend a header to each chunk.
    Splits chunks at rows that are all NaN (empty or whitespace-only).
    """
    chunks = []
    current_chunk = []
    current_length = 0
    if header:
        header_length = len(header) + 1  # +1 for newline
    else:
        header_length = 0

    for i, row in enumerate(rows):
        row_length = len(row) + 1  # +1 for newline

        # Check if this row is all NaN (empty or whitespace-only)
        is_nan_row = (
            not row.strip()
            or row.strip() == "nan"
            or all(cell.strip() == "nan" for cell in row.split(" | "))
        )

        # If we have a current chunk and encounter a NaN row, start a new chunk
        if is_nan_row and current_chunk:
            chunk = (
                "\n".join([header] + current_chunk)
                if header
                else "\n".join(current_chunk)
            )
            chunks.append(chunk)
            current_chunk = []
            current_length = 0
            continue  # Skip adding the NaN row to chunks

        # Check if adding this row would exceed chunk size
        if current_length + row_length + header_length > chunk_size and current_chunk:
            # Start a new chunk
            chunk = (
                "\n".join([header] + current_chunk)
                if header
                else "\n".join(current_chunk)
            )
            chunks.append(chunk)
            current_chunk = []
            current_length = 0

        # Only add non-NaN rows to chunks
        if not is_nan_row:
            current_chunk.append(row)
            current_length += row_length

    # Add the last chunk if it exists
    if current_chunk:
        chunk = (
            "\n".join([header] + current_chunk) if header else "\n".join(current_chunk)
        )
        chunks.append(chunk)

    return chunks


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """A markdown table with a header row, as stored for re-chunking tabular files."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


class CSVTextExtractor(BaseFileExtractor):
    @staticmethod
    def _read_rows(content: bytes) -> Optional[Tuple[List[str], List[List[str]]]]:
        """``(column names, rows of cell strings with 'nan' for empty cells)``, or ``None`` if empty."""
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                csv_text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            csv_text = content.decode("utf-8", errors="ignore")
        df = pd.read_csv(io.StringIO(csv_text))
        if df.empty:
            return None
        # Convert each cell to string, handling NaN values
        rows = [["nan" if pd.isna(cell) else str(cell) for cell in row] for _, row in df.iterrows()]
        return [str(column) for column in df.columns], rows

    async def extract(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        try:
            table = self._read_rows(content)
        except Exception:
            logger.exception("CSV text extraction failed for %s", filename)
            return Extraction([], "")
        if table is None:
            return Extraction([], "")
        columns, rows = table
        header = f"Columns: {' | '.join(columns)}"
        chunks = smart_chunk_rows([" | ".join(row) for row in rows], chunk_size=FALLBACK_CHUNK_SIZE, header=header)
        return Extraction(chunks, markdown_table(columns, rows))


class XLSXTextExtractor(BaseFileExtractor):
    """
    Extracts one chunk per worksheet from ``.xlsx``.

    Legacy ``.xls`` is not supported: it is an OLE2 binary that openpyxl cannot
    read (it raises ``BadZipFile``), and that format is excluded from
    ``ALLOWED_EXTENSIONS`` alongside ``.doc``. Save such files as ``.xlsx``.
    """

    @staticmethod
    def _load_sheets(content: bytes) -> list:
        """
        Read a workbook into ``[(sheet_name, [row_tuple, ...]), ...]``.

        Args:
            content: Raw ``.xlsx`` bytes.

        Returns:
            One ``(name, rows)`` pair per worksheet.
        """
        # data_only=True yields cached evaluated values instead of formulas
        workbook = load_workbook(io.BytesIO(content), data_only=True)
        return [
            (ws.title, list(ws.iter_rows(values_only=True)))
            for ws in workbook.worksheets
        ]

    @staticmethod
    def _format_cell(cell) -> str:
        """A cell as Excel displays it (numbers rounded to 2 decimals); ``nan`` when empty."""
        if cell is None:
            return "nan"
        if isinstance(cell, (int, float)):
            if isinstance(cell, float) and cell.is_integer():
                return str(int(cell))
            return f"{cell:.2f}"
        return str(cell)

    def _sheet_tables(self, content: bytes) -> List[Tuple[str, List[str], List[List[str]]]]:
        """``(sheet name, headers, non-empty rows)`` for every sheet that has data."""
        tables = []
        for sheet_name, values in self._load_sheets(content):
            # Derive headers from first non-empty row; fallback to generic names
            header_index = next(
                (i for i, r in enumerate(values) if any(cell is not None and str(cell).strip() != "" for cell in r)),
                None,
            )
            if header_index is None:
                continue
            headers = [
                (str(h).strip() if h is not None and str(h).strip() != "" else f"col_{i+1}")
                for i, h in enumerate(values[header_index])
            ]
            rows = []
            for r in values[header_index + 1:]:
                cells = [self._format_cell(cell) for cell in r[: len(headers)]]
                # Skip completely empty rows
                if sum(1 for cell in r[: len(headers)] if cell is None) != len(headers):
                    rows.append(cells)
            if rows:
                tables.append((sheet_name, headers, rows))
        return tables

    async def extract(self, content: bytes, filename: Optional[str] = None) -> Extraction:
        try:
            tables = self._sheet_tables(content)
        except Exception:
            logger.exception("XLSX text extraction failed for %s", filename)
            return Extraction([], "")
        # Keep each sheet as one complete chunk instead of splitting by size
        chunks = [
            "\n".join([f"Sheet: {name}\nColumns: {' | '.join(headers)}"] + [" | ".join(row) for row in rows])
            for name, headers, rows in tables
        ]
        text = "\n\n".join(f"## Sheet: {name}\n{markdown_table(headers, rows)}" for name, headers, rows in tables)
        return Extraction(chunks, text)


def smart_chunk_text(text, chunk_size=1000, overlap=200):
    """
    Chunk narrative text, avoiding splitting in the middle of sentences.
    Delegates to TextUtils.chunk_text for unified chunking logic.
    """
    from utils.text_utils import TextUtils

    return TextUtils.chunk_text(text, chunk_size=chunk_size, overlap=overlap)
