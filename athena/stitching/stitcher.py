#!/usr/bin/env python3
"""
Module: Stitcher
Purpose: ATHENA Table Stitcher.

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

import logging
import re
from datetime import datetime
from typing import Optional

from athena.core.models.cell import TableCell
from athena.core.models.grid import TableGrid
from athena.stitching.models import LogicalTable, StitchMatch, StitchSignal

__all__ = ["TableStitcher"]
__safety_critical__ = True

logger = logging.getLogger(__name__)

# Patterns for continuation detection
CONTINUATION_PATTERNS = [
    re.compile(r"\(cont\.?\)", re.IGNORECASE),
    re.compile(r"\(continued\)", re.IGNORECASE),
    re.compile(r"continued\s+from", re.IGNORECASE),
    re.compile(r"table\s+\d+\s*\(cont", re.IGNORECASE),
]


class TableStitcher:
    """
    Stitches multi-page tables into LogicalTable objects.

    Detection signals:
    1. Header matching - identical column headers
    2. Continuation text - "(cont.)", "(continued)", etc.
    3. BBox position - same x-position on page
    4. Page sequence - consecutive pages
    5. Column count - same number of columns
    """

    def __init__(
        self,
        header_match_threshold: float = 0.8,
        bbox_x_tolerance: float = 20.0,  # points
        min_stitch_confidence: float = 0.5,
    ):
        self.header_match_threshold = header_match_threshold
        self.bbox_x_tolerance = bbox_x_tolerance
        self.min_stitch_confidence = min_stitch_confidence
        self.logger = logging.getLogger(self.__class__.__name__)

    def stitch(self, grids: list[TableGrid]) -> list[LogicalTable]:
        """
        Stitch a list of TableGrids into LogicalTables.

        Tables are merged when continuation signals are detected.
        Single-page tables are wrapped as LogicalTable.

        Args:
            grids: List of TableGrid objects, typically from a single PDF

        Returns:
            List of LogicalTable objects (may be fewer than input if stitched)
        """
        if not grids:
            return []

        # Sort by page number, then by table index
        sorted_grids = sorted(
            grids,
            key=lambda g: (g.source.page_number, g.source.table_index)
        )

        logical_tables: list[LogicalTable] = []
        current_chain: list[TableGrid] = []

        for grid in sorted_grids:
            if not current_chain:
                # Start new chain
                current_chain.append(grid)
                continue

            # Check if this grid continues the current chain
            match = self._check_continuation(current_chain[-1], grid)

            if match and match.confidence >= self.min_stitch_confidence:
                # Continue the chain
                current_chain.append(grid)
                self.logger.debug(
                    f"Stitching {grid.table_id} to chain "
                    f"(signals: {[s.value for s in match.signals]}, "
                    f"confidence: {match.confidence:.2f})"
                )
            else:
                # End current chain, start new one
                logical_tables.append(self._merge_chain(current_chain))
                current_chain = [grid]

        # Don't forget the last chain
        if current_chain:
            logical_tables.append(self._merge_chain(current_chain))

        self.logger.info(
            f"Stitched {len(grids)} grids into {len(logical_tables)} logical tables"
        )

        return logical_tables

    def _check_continuation(
        self,
        source: TableGrid,
        target: TableGrid,
    ) -> Optional[StitchMatch]:
        """
        Check if target is a continuation of source.

        Returns StitchMatch with detected signals, or None if no match.
        """
        signals: list[StitchSignal] = []

        # Signal 1: Page sequence (consecutive pages)
        if target.source.page_number == source.source.page_number + 1:
            signals.append(StitchSignal.PAGE_SEQUENCE)

        # Signal 2: Column count match
        if target.col_count == source.col_count:
            signals.append(StitchSignal.COLUMN_COUNT)

        # Signal 3: Header matching
        if self._headers_match(source, target):
            signals.append(StitchSignal.HEADER_MATCH)

        # Signal 4: Continuation text in context or first row
        if self._has_continuation_text(target):
            signals.append(StitchSignal.CONTINUATION_TEXT)

        # Signal 5: BBox position continuity (same x-position)
        if self._bbox_position_matches(source, target):
            signals.append(StitchSignal.BBOX_POSITION)

        if not signals:
            return None

        return StitchMatch(
            source_grid=source,
            target_grid=target,
            signals=signals,
        )

    def _headers_match(self, source: TableGrid, target: TableGrid) -> bool:
        """Check if headers match between tables."""
        if source.col_count != target.col_count:
            return False

        source_headers = source.get_all_header_signatures()
        target_headers = target.get_all_header_signatures()

        if not source_headers or not target_headers:
            return False

        # Normalize headers for comparison
        def normalize(h: str) -> str:
            return re.sub(r"\s+", " ", h.lower().strip())

        matches = sum(
            1 for s, t in zip(source_headers, target_headers)
            if normalize(s) == normalize(t) and s.strip()
        )

        # Require threshold of non-empty headers to match
        non_empty = sum(1 for h in source_headers if h.strip())
        if non_empty == 0:
            return False

        match_ratio = matches / non_empty
        return match_ratio >= self.header_match_threshold

    def _has_continuation_text(self, grid: TableGrid) -> bool:
        """Check for continuation markers in table context or headers."""
        # Check context text
        if grid.context_text:
            for pattern in CONTINUATION_PATTERNS:
                if pattern.search(grid.context_text):
                    return True

        # Check first header row
        for c in range(grid.col_count):
            cell = grid.get_cell(0, c)
            if cell and cell.text:
                for pattern in CONTINUATION_PATTERNS:
                    if pattern.search(cell.text):
                        return True

        return False

    def _bbox_position_matches(self, source: TableGrid, target: TableGrid) -> bool:
        """Check if tables are at similar x-positions."""
        source_bbox = source.source.bbox
        target_bbox = target.source.bbox

        if source_bbox is None or target_bbox is None:
            return False

        # Compare x0 positions (left edge)
        x_diff = abs(source_bbox.x0 - target_bbox.x0)
        return x_diff <= self.bbox_x_tolerance

    def _merge_chain(self, chain: list[TableGrid]) -> LogicalTable:
        """Merge a chain of TableGrids into a LogicalTable."""
        if len(chain) == 1:
            return LogicalTable.from_single_grid(chain[0])

        # Use first grid as base
        first = chain[0]

        # Collect all stitch signals used
        all_signals: set[StitchSignal] = set()
        min_confidence = 1.0

        for i in range(len(chain) - 1):
            match = self._check_continuation(chain[i], chain[i + 1])
            if match:
                all_signals.update(match.signals)
                min_confidence = min(min_confidence, match.confidence)

        # Merge cells, offsetting rows for continuation tables
        merged_cells: list[TableCell] = []
        current_row_offset = 0

        for idx, grid in enumerate(chain):
            if idx == 0:
                # First table: include all cells
                for cell in grid.cells:
                    merged_cells.append(TableCell(
                        r=cell.r,
                        c=cell.c,
                        text=cell.text,
                        rowspan=cell.rowspan,
                        colspan=cell.colspan,
                        semantic_tag=cell.semantic_tag,
                    ))
                current_row_offset = grid.row_count
            else:
                # Continuation: skip header rows, offset data rows
                data_start = grid.header_row_count
                for cell in grid.cells:
                    if cell.r >= data_start:
                        merged_cells.append(TableCell(
                            r=current_row_offset + (cell.r - data_start),
                            c=cell.c,
                            text=cell.text,
                            rowspan=cell.rowspan,
                            colspan=cell.colspan,
                            semantic_tag=cell.semantic_tag,
                        ))
                # Add data rows from this grid
                current_row_offset += (grid.row_count - data_start)

        # Calculate total row count
        total_rows = current_row_offset

        # Collect footnotes from all grids
        all_footnotes = []
        for grid in chain:
            if grid.footnotes_text:
                all_footnotes.append(grid.footnotes_text)

        return LogicalTable(
            table_id=first.table_id,  # Keep first table's ID
            cells=merged_cells,
            row_count=total_rows,
            col_count=first.col_count,
            header_row_count=first.header_row_count,
            context_text=first.context_text,
            footnotes_text="\n".join(all_footnotes) if all_footnotes else None,
            source_grids=chain,
            page_range=(
                chain[0].source.page_number,
                chain[-1].source.page_number,
            ),
            stitch_signals=list(all_signals),
            stitch_confidence=min_confidence,
            extraction_confidence=min(g.extraction_confidence for g in chain),
            extraction_timestamp=datetime.now().isoformat(),
        )
