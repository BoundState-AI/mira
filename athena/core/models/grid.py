#!/usr/bin/env python3
"""
Module: Grid
Purpose: TableGrid Model.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, PrivateAttr, computed_field

from athena.core.models.cell import TableCell
from athena.core.models.source import TableSource

__all__ = ["TableGrid"]
__safety_critical__ = True


class TableGrid(BaseModel):
    """
    Single table extracted as lossless cell grid.

    Compliance: SWE-032 (data integrity), SWE-033 (traceability)
    """
    model_config = {"extra": "forbid"}

    table_id: str
    cells: list[TableCell]
    row_count: int
    col_count: int
    header_row_count: int = 1

    context_text: Optional[str] = None
    footnotes_text: Optional[str] = None

    source: TableSource

    # Quality
    extraction_confidence: float = 1.0
    extraction_timestamp: str
    error: Optional[str] = None

    # Internal index for O(1) cell lookup
    _cell_index: dict[tuple[int, int], TableCell] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Build cell index after initialization."""
        self._build_cell_index()

    def _build_cell_index(self) -> None:
        """Build O(1) lookup index for cells, handling spans."""
        self._cell_index = {}
        for cell in self.cells:
            # Index the cell at its primary position
            self._cell_index[(cell.r, cell.c)] = cell
            # Also index all positions covered by spans
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    pos = (cell.r + dr, cell.c + dc)
                    if pos not in self._cell_index:
                        self._cell_index[pos] = cell

    def get_cell(self, row: int, col: int) -> Optional[TableCell]:
        """O(1) cell lookup."""
        return self._cell_index.get((row, col))

    def get_row(self, row: int) -> list[Optional[str]]:
        """Get all text values in a row."""
        return [
            cell.text if (cell := self.get_cell(row, c)) else None
            for c in range(self.col_count)
        ]

    def get_column_header_signature(self, col: int) -> str:
        """
        Construct header signature from ALL header rows.

        Example: "Mechanical Properties | RA (%)"
        """
        parts = []
        seen = set()

        for r in range(self.header_row_count):
            cell = self.get_cell(r, col)
            if cell and cell.text and cell.text.strip():
                text = cell.text.strip()
                if text not in seen:
                    parts.append(text)
                    seen.add(text)

        return " | ".join(parts) if parts else ""

    def get_all_header_signatures(self) -> list[str]:
        """Get header signatures for all columns."""
        return [self.get_column_header_signature(c) for c in range(self.col_count)]

    def get_column_headers_flat(self) -> list[str]:
        """Get bottom header row only."""
        if self.header_row_count == 0:
            return []
        return [h or "" for h in self.get_row(self.header_row_count - 1)]

    def get_data_rows(self) -> list[list[Optional[str]]]:
        """Get data rows EXCLUDING headers."""
        return [
            self.get_row(r)
            for r in range(self.header_row_count, self.row_count)
        ]

    @computed_field
    @property
    def structural_coverage(self) -> float:
        """
        Structural coverage metric for confidence.

        1.0 = all expected positions covered
        """
        expected = self.row_count * self.col_count
        if expected == 0:
            return 0.0

        covered = len(set(self._cell_index.keys()))
        return min(1.0, covered / expected)
