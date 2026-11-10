"""
Minimal markdown-table helpers shared by the table-aware chunking strategies.
"""

# Standard library imports
import re
from typing import List, Optional

SEPARATOR_ROW_PATTERN = re.compile(r"^\|?[\s:\-|]+\|?$")
#: Cell values pandas/Docling write for empty spreadsheet cells.
EMPTY_CELL_VALUES = {"", "nan", "none"}


def table_cells(line: str) -> Optional[List[str]]:
    """Cells of a markdown table row, or ``None`` if ``line`` is not a table row."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")) or len(stripped) < 2:
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def is_separator_row(line: str) -> bool:
    """True for a header separator such as ``|---|:---:|``."""
    stripped = line.strip()
    return bool(stripped) and "-" in stripped and bool(SEPARATOR_ROW_PATTERN.match(stripped))


def is_empty_row(cells: List[str]) -> bool:
    """True when every cell is blank or a NaN placeholder."""
    return all(cell.lower() in EMPTY_CELL_VALUES for cell in cells)
