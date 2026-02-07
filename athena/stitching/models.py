#!/usr/bin/env python3
"""
Module: Models
Purpose: ATHENA Stitching Models.

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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, PrivateAttr, computed_field

from athena.core.models.cell import TableCell
from athena.core.models.grid import TableGrid
from athena.core.models.source import TableSource

__all__ = ["LogicalTable", "StitchSignal", "StitchMatch"]
__safety_critical__ = True


class StitchSignal(str, Enum):
    """Signals used to detect table continuations."""
    HEADER_MATCH = "header_match"          # Headers match across pages
    CONTINUATION_TEXT = "continuation_text"  # "(cont.)", "(continued)", etc.
    BBOX_POSITION = "bbox_position"        # Table at same x-position
    PAGE_SEQUENCE = "page_sequence"        # Consecutive pages
    COLUMN_COUNT = "column_count"          # Same number of columns


@dataclass
class StitchMatch:
    """Represents a match between two TableGrids for stitching."""
    source_grid: TableGrid
    target_grid: TableGrid
    signals: list[StitchSignal]
    confidence: float = 0.0

    def __post_init__(self) -> None:
        """Calculate confidence from signals."""
        if not self.signals:
            self.confidence = 0.0
            return

        # Weight each signal
        weights = {
            StitchSignal.HEADER_MATCH: 0.4,
            StitchSignal.CONTINUATION_TEXT: 0.3,
            StitchSignal.BBOX_POSITION: 0.15,
            StitchSignal.PAGE_SEQUENCE: 0.1,
            StitchSignal.COLUMN_COUNT: 0.05,
        }
        self.confidence = sum(weights.get(s, 0) for s in self.signals)


class LogicalTable(BaseModel):
    """
    A logical table that may span multiple physical pages.

    Combines multiple TableGrids into a unified structure.
    """
    model_config = {"extra": "forbid"}

    table_id: str
    cells: list[TableCell]
    row_count: int
    col_count: int
    header_row_count: int = 1

    context_text: Optional[str] = None
    footnotes_text: Optional[str] = None

    # Source grids that were stitched
    source_grids: list[TableGrid]

    # Stitching metadata
    page_range: tuple[int, int]  # (first_page, last_page)
    stitch_signals: list[StitchSignal] = Field(default_factory=list)
    stitch_confidence: float = 1.0

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
            self._cell_index[(cell.r, cell.c)] = cell
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
        """Construct header signature from ALL header rows."""
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

    def get_data_rows(self) -> list[list[Optional[str]]]:
        """Get data rows EXCLUDING headers."""
        return [
            self.get_row(r)
            for r in range(self.header_row_count, self.row_count)
        ]

    @computed_field
    @property
    def structural_coverage(self) -> float:
        """Structural coverage metric."""
        expected = self.row_count * self.col_count
        if expected == 0:
            return 0.0
        covered = len(set(self._cell_index.keys()))
        return min(1.0, covered / expected)

    @computed_field
    @property
    def is_multi_page(self) -> bool:
        """True if table spans multiple pages."""
        return len(self.source_grids) > 1

    @computed_field
    @property
    def page_count(self) -> int:
        """Number of pages this table spans."""
        return self.page_range[1] - self.page_range[0] + 1

    @classmethod
    def from_single_grid(cls, grid: TableGrid) -> LogicalTable:
        """Create a LogicalTable from a single TableGrid (no stitching)."""
        return cls(
            table_id=grid.table_id,
            cells=grid.cells.copy(),
            row_count=grid.row_count,
            col_count=grid.col_count,
            header_row_count=grid.header_row_count,
            context_text=grid.context_text,
            footnotes_text=grid.footnotes_text,
            source_grids=[grid],
            page_range=(grid.source.page_number, grid.source.page_number),
            stitch_signals=[],
            stitch_confidence=1.0,
            extraction_confidence=grid.extraction_confidence,
            extraction_timestamp=grid.extraction_timestamp,
            error=grid.error,
        )
