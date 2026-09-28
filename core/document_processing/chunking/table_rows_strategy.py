"""
Table chunking for spreadsheets and tabular documents: groups of rows, header repeated.
"""

# Standard library imports
import re
from typing import List, Optional

# Local imports
from models.knowledge import ChunkDraft
from .markdown_tables import is_empty_row, is_separator_row, table_cells
from .size_strategy import SizeChunker

#: A heading naming a spreadsheet sheet, as the local XLSX extractor writes it.
SHEET_HEADING_PATTERN = re.compile(r"^#{1,6}\s*Sheet:\s*(.+\S)", re.IGNORECASE)


class TableRowsChunker:
    """Every ``rows_per_chunk`` table rows become one chunk that starts with the table's header row."""

    def __init__(self, rows_per_chunk: int = 10, max_chars: int = 3000):
        """
        Args:
            rows_per_chunk: Data rows per chunk.
            max_chars: Size cap for the text between tables.
        """
        self._rows_per_chunk = rows_per_chunk
        self._max_chars = max_chars

    def split(self, text: str) -> List[ChunkDraft]:
        """
        Split ``text``; tables by row groups, other text by size.

        Returns:
            Chunks in order. Table chunks carry ``rows`` ("11-20", counting data
            rows from 1) and ``sheet`` when a ``## Sheet: <name>`` heading precedes them.
        """
        drafts: List[ChunkDraft] = []
        prose: List[str] = []
        table: List[str] = []
        sheet: Optional[str] = None

        def flush_prose() -> None:
            if "\n".join(prose).strip():
                drafts.extend(SizeChunker(self._max_chars).split("\n".join(prose)))
            prose.clear()

        def flush_table() -> None:
            if table:
                drafts.extend(self._table_drafts(table, sheet))
            table.clear()

        for line in text.splitlines():
            if table_cells(line) is not None:
                flush_prose()
                table.append(line)
                continue
            flush_table()
            sheet_match = SHEET_HEADING_PATTERN.match(line.strip())
            if sheet_match:
                flush_prose()
                sheet = sheet_match.group(1)
                continue
            prose.append(line)
        flush_table()
        flush_prose()
        return drafts

    def _table_drafts(self, lines: List[str], sheet: Optional[str]) -> List[ChunkDraft]:
        """Row groups of one table; the first row is taken as its header."""
        rows = [line.strip() for line in lines if not is_separator_row(line)]
        header, data = rows[0], [row for row in rows[1:] if not is_empty_row(table_cells(row) or [])]
        if not data:
            return [ChunkDraft(header, {"sheet": sheet} if sheet else {})]
        drafts: List[ChunkDraft] = []
        for start in range(0, len(data), self._rows_per_chunk):
            group = data[start:start + self._rows_per_chunk]
            metadata = {"rows": f"{start + 1}-{start + len(group)}"}
            if sheet:
                metadata["sheet"] = sheet
            drafts.append(ChunkDraft("\n".join([header, *group]), metadata))
        return drafts
