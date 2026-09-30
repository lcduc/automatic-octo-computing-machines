"""
Table chunking for spreadsheets and tabular documents: groups of rows, header repeated.
"""

# Standard library imports
import re
from typing import Dict, List, Optional

# Local imports
from models.knowledge import ChunkDraft
from .heading_strategy import HEADING_PATTERN, MAX_HEADING_METADATA_CHARS
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

        A heading line right above a table is its caption: it leaves the prose
        and starts every chunk of that table (like the header row), so a row
        group still says what the table is about.

        Returns:
            Chunks in order. Table chunks carry ``rows`` ("11-20", counting data
            rows from 1), ``sheet`` when a ``## Sheet: <name>`` heading precedes
            them and ``heading`` when a caption does.
        """
        drafts: List[ChunkDraft] = []
        prose: List[str] = []
        table: List[str] = []
        sheet: Optional[str] = None
        caption: Optional[str] = None

        def flush_prose() -> None:
            if "\n".join(prose).strip():
                drafts.extend(SizeChunker(self._max_chars).split("\n".join(prose)))
            prose.clear()

        def flush_table() -> None:
            nonlocal caption
            if table:
                drafts.extend(self._table_drafts(table, sheet, caption))
            table.clear()
            caption = None

        def take_caption() -> Optional[str]:
            """Pop the heading line (if any) that ends the prose before a table."""
            while prose and not prose[-1].strip():
                prose.pop()
            if prose and HEADING_PATTERN.match(prose[-1].strip()):
                return prose.pop().strip()
            return None

        for line in text.splitlines():
            if table_cells(line) is not None:
                if not table:
                    caption = take_caption()
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

    def _table_drafts(self, lines: List[str], sheet: Optional[str], caption: Optional[str]) -> List[ChunkDraft]:
        """Row groups of one table; the first row is taken as its header, preceded by the caption."""
        rows = [line.strip() for line in lines if not is_separator_row(line)]
        header, data = rows[0], [row for row in rows[1:] if not is_empty_row(table_cells(row) or [])]
        lead = [caption, header] if caption else [header]
        context: Dict[str, str] = {}
        if sheet:
            context["sheet"] = sheet
        if caption:
            context["heading"] = HEADING_PATTERN.match(caption).group(2)[:MAX_HEADING_METADATA_CHARS]
        if not data:
            return [ChunkDraft("\n".join(lead), context)]
        drafts: List[ChunkDraft] = []
        for start in range(0, len(data), self._rows_per_chunk):
            group = data[start:start + self._rows_per_chunk]
            drafts.append(ChunkDraft("\n".join([*lead, *group]), {"rows": f"{start + 1}-{start + len(group)}", **context}))
        return drafts
