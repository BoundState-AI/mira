#!/usr/bin/env python3
"""
Module: Extractor V10
Purpose: bok_extractor_v10

BoundState AI 2025
Version: 0.10.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

import pdfplumber
from pydantic import BaseModel, Field, PrivateAttr, computed_field
import uuid

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

__all__ = [
    "TableExtractorV10",
    "TableGrid",
    "TableCell",
    "BBox",
    "TableSource",
    "ExtractionResult",
    "extract_tables",
]
__safety_critical__ = True

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core Models (ATHENA v1.4 Spec)
# ---------------------------------------------------------------------------

class CoordSpace(str, Enum):
    """Coordinate space for bounding boxes."""
    PDF_POINTS = "pdf_points"
    PAGE_PIXELS = "page_pixels"


class Origin(str, Enum):
    """Origin position for coordinate system."""
    BOTTOM_LEFT = "bottom_left"  # PDF standard
    TOP_LEFT = "top_left"        # Image standard


class BBox(BaseModel):
    """
    Bounding box with explicit coordinate system (Fran Fix #1).

    Never pass raw tuples. Always specify coord_space, origin, and dpi.
    """
    model_config = {"extra": "forbid"}

    x0: float
    y0: float
    x1: float
    y1: float
    coord_space: CoordSpace = CoordSpace.PDF_POINTS
    origin: Origin = Origin.BOTTOM_LEFT
    dpi: Optional[int] = None  # Required if coord_space == PAGE_PIXELS

    @classmethod
    def from_tuple(
        cls,
        bbox: tuple[float, float, float, float],
        coord_space: CoordSpace = CoordSpace.PDF_POINTS,
        origin: Origin = Origin.BOTTOM_LEFT,
        dpi: Optional[int] = None,
    ) -> "BBox":
        """Create BBox from tuple."""
        return cls(
            x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
            coord_space=coord_space, origin=origin, dpi=dpi
        )

    def to_tuple(self) -> tuple[float, float, float, float]:
        """Convert to tuple."""
        return (self.x0, self.y0, self.x1, self.y1)

    def to_pdf_points(self, page_height: float) -> "BBox":
        """Convert to PDF points coordinate space."""
        if self.coord_space == CoordSpace.PDF_POINTS:
            return self

        if self.dpi is None:
            raise ValueError("dpi required for pixel to points conversion")

        scale = 72.0 / self.dpi

        if self.origin == Origin.TOP_LEFT:
            # Convert from top-left to bottom-left origin
            return BBox(
                x0=self.x0 * scale,
                y0=page_height - (self.y1 * scale),
                x1=self.x1 * scale,
                y1=page_height - (self.y0 * scale),
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
                dpi=None,
            )
        else:
            return BBox(
                x0=self.x0 * scale,
                y0=self.y0 * scale,
                x1=self.x1 * scale,
                y1=self.y1 * scale,
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
                dpi=None,
            )

    def to_page_pixels(self, page_height: float, dpi: int = 150) -> "BBox":
        """Convert to page pixels coordinate space."""
        if self.coord_space == CoordSpace.PAGE_PIXELS and self.dpi == dpi:
            return self

        # First ensure we're in PDF points
        if self.coord_space == CoordSpace.PAGE_PIXELS:
            pdf_bbox = self.to_pdf_points(page_height)
        else:
            pdf_bbox = self

        scale = dpi / 72.0

        # Convert to top-left origin for image coordinates
        return BBox(
            x0=pdf_bbox.x0 * scale,
            y0=(page_height - pdf_bbox.y1) * scale,
            x1=pdf_bbox.x1 * scale,
            y1=(page_height - pdf_bbox.y0) * scale,
            coord_space=CoordSpace.PAGE_PIXELS,
            origin=Origin.TOP_LEFT,
            dpi=dpi,
        )


class TableSource(BaseModel):
    """Provenance tracking for extracted table."""
    model_config = {"extra": "forbid"}

    document_path: str
    document_name: str
    page_number: int  # 1-indexed
    table_index: int  # 0-indexed within page
    bbox: BBox
    page_width: float
    page_height: float

    # Optional debug artifacts
    image_path: Optional[str] = None
    image_size_kb: float = 0.0


class TableCell(BaseModel):
    """
    A single cell in a table grid.

    Uses (row, col) position instead of header key to handle:
    - Duplicate headers
    - Multi-row headers
    - Blank headers
    - Spanning cells
    """
    model_config = {"extra": "forbid"}

    row: int  # 0-indexed
    col: int  # 0-indexed
    text: Optional[str] = None

    # For merged/spanning cells
    row_span: int = 1
    col_span: int = 1

    # Cell-level metadata
    is_header: bool = False

    def __hash__(self):
        return hash((self.row, self.col))


class TableGrid(BaseModel):
    """
    A table as a grid of cells (ATHENA v1.4 spec).

    Key insight: dict-by-header breaks on duplicate headers, multi-row headers,
    blank headers, spanning headers. Grid structure handles all cases.

    Features:
    - O(1) cell lookup via _cell_index built on init (Fran Fix #8)
    - structural_coverage for confidence calculation (Fran Fix #6)
    - header_rows for multi-row header support
    """
    model_config = {"extra": "forbid"}

    table_id: str
    source: TableSource

    # Grid structure
    cells: list[TableCell] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    header_rows: int = 1  # Number of header rows (typically 1-3)

    # Context
    caption: Optional[str] = None
    footnotes: Optional[str] = None

    # Extraction metadata
    extraction_time_ms: float = 0.0
    confidence: float = 1.0
    error: Optional[str] = None
    raw_response: Optional[str] = None

    # Internal index for O(1) lookup (private attribute)
    _cell_index: dict[tuple[int, int], TableCell] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Build cell index after initialization."""
        self._build_cell_index()

    def _build_cell_index(self) -> None:
        """Build O(1) lookup index."""
        self._cell_index = {(c.row, c.col): c for c in self.cells}

    def get_cell(self, row: int, col: int) -> Optional[TableCell]:
        """O(1) cell lookup."""
        return self._cell_index.get((row, col))

    def get_header_row(self, header_row: int = 0) -> list[TableCell]:
        """Get cells from a specific header row."""
        return sorted(
            [c for c in self.cells if c.row == header_row and c.is_header],
            key=lambda c: c.col
        )

    def get_column_headers(self) -> list[str]:
        """Get flattened column headers (first header row)."""
        headers = self.get_header_row(0)
        return [h.text or "" for h in headers]

    def get_data_rows(self) -> list[list[TableCell]]:
        """Get data rows (excludes header rows)."""
        data_cells = [c for c in self.cells if c.row >= self.header_rows]
        rows: dict[int, list[TableCell]] = {}
        for cell in data_cells:
            if cell.row not in rows:
                rows[cell.row] = []
            rows[cell.row].append(cell)

        return [
            sorted(rows[r], key=lambda c: c.col)
            for r in sorted(rows.keys())
        ]

    def get_all_rows_with_headers(self) -> list[list[TableCell]]:
        """Get all rows including headers (for stitching)."""
        rows: dict[int, list[TableCell]] = {}
        for cell in self.cells:
            if cell.row not in rows:
                rows[cell.row] = []
            rows[cell.row].append(cell)

        return [
            sorted(rows[r], key=lambda c: c.col)
            for r in sorted(rows.keys())
        ]

    @computed_field
    @property
    def structural_coverage(self) -> float:
        """
        Compute structural coverage for confidence (Fran Fix #6).

        1.0 = All cells have valid (r,c) within bounds, no overlaps
        Lower scores indicate structural issues.
        """
        if self.row_count == 0 or self.col_count == 0:
            return 0.0

        expected_cells = self.row_count * self.col_count
        actual_cells = len(self.cells)

        # Check for cells within bounds
        valid_cells = sum(
            1 for c in self.cells
            if 0 <= c.row < self.row_count and 0 <= c.col < self.col_count
        )

        # Check for duplicates (overlapping cells)
        positions = [(c.row, c.col) for c in self.cells]
        unique_positions = len(set(positions))

        # Coverage score
        if actual_cells == 0:
            return 0.0

        bounds_score = valid_cells / actual_cells
        duplicate_score = unique_positions / actual_cells
        fill_score = min(1.0, actual_cells / expected_cells)

        return (bounds_score + duplicate_score + fill_score) / 3


class ExtractionResult(BaseModel):
    """Result of extracting tables from document(s)."""
    model_config = {"extra": "forbid"}

    extraction_timestamp: str
    extractor_version: str = "0.10.0"
    source: str

    # Stats
    documents_processed: int = 0
    pages_processed: int = 0
    tables_found_pdfplumber: int = 0
    tables_found_vision: int = 0
    tables_extracted: int = 0
    tables_failed: int = 0
    total_rows: int = 0
    api_calls: int = 0
    total_time_seconds: float = 0.0

    # Data
    tables: list[TableGrid] = Field(default_factory=list)
    failed_documents: list[str] = Field(default_factory=list)

    # Validation
    validation_passed: bool = True
    validation_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Extraction Prompt - Returns Grid Structure
# ---------------------------------------------------------------------------

TABLE_EXTRACTION_PROMPT = """Read this table image and return the exact grid structure.

Return JSON in this format:
{
  "row_count": 5,
  "col_count": 3,
  "header_rows": 1,
  "cells": [
    {"row": 0, "col": 0, "text": "Header1", "is_header": true},
    {"row": 0, "col": 1, "text": "Header2", "is_header": true},
    {"row": 0, "col": 2, "text": "Header3", "is_header": true},
    {"row": 1, "col": 0, "text": "Value1"},
    {"row": 1, "col": 1, "text": "Value2"},
    {"row": 1, "col": 2, "text": "Value3"}
  ],
  "caption": "Table title if visible above table",
  "footnotes": "Any footnotes below table"
}

RULES:
- Count rows and columns FIRST, then fill cells
- Row 0 is the first row (typically header)
- Col 0 is the first column (typically leftmost)
- Extract EVERY cell - use null for empty cells
- Preserve text exactly as shown (numbers, symbols, units, line breaks)
- If a cell spans multiple rows/columns, add row_span/col_span
- If there are multiple header rows, set header_rows accordingly
- Mark header cells with is_header: true
- Include table caption if visible above table
- Include footnotes if visible below table
- Do NOT interpret, calculate, or infer meaning
- Do NOT skip rows even if they look like duplicates

Return ONLY the JSON object, no other text."""


# ---------------------------------------------------------------------------
# Vision Detection Prompt (for when pdfplumber finds 0 tables)
# ---------------------------------------------------------------------------

TABLE_DETECTION_PROMPT = """Find all tables in this page image.

For each table, return its bounding box as [x0, y0, x1, y1] in pixels from top-left.

Return JSON:
{
  "tables": [
    {"bbox": [100, 200, 500, 600], "description": "Materials properties table"},
    {"bbox": [100, 700, 500, 900], "description": "Test results table"}
  ]
}

RULES:
- Find ALL tables including small ones
- bbox is [left, top, right, bottom] in pixels
- Include table description to help identify it
- If no tables found, return {"tables": []}

Return ONLY the JSON object."""


# ---------------------------------------------------------------------------
# Image Rendering
# ---------------------------------------------------------------------------

def render_table_image(
    page: pdfplumber.page.Page,
    bbox: BBox,
    resolution: int = 150,
    padding: int = 15,
) -> bytes:
    """Render a table region to PNG bytes."""
    # Convert to PDF points if needed
    pdf_bbox = bbox.to_pdf_points(page.height) if bbox.coord_space != CoordSpace.PDF_POINTS else bbox

    x0, y0, x1, y1 = pdf_bbox.to_tuple()
    page_height = page.height
    page_width = page.width

    # Add padding in page units
    pad_units = padding * 72 / resolution
    x0 = max(0, x0 - pad_units)
    y0 = max(0, y0 - pad_units)
    x1 = min(page_width, x1 + pad_units)
    y1 = min(page_height, y1 + pad_units)

    cropped = page.crop((x0, y0, x1, y1))
    img = cropped.to_image(resolution=resolution)

    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    return img_bytes.getvalue()


def render_full_page(page: pdfplumber.page.Page, resolution: int = 150) -> bytes:
    """Render full page to PNG bytes for table detection."""
    img = page.to_image(resolution=resolution)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    return img_bytes.getvalue()


def image_to_base64(img_bytes: bytes) -> str:
    """Convert image bytes to base64 string."""
    return base64.standard_b64encode(img_bytes).decode("utf-8")


# ---------------------------------------------------------------------------
# Vision API
# ---------------------------------------------------------------------------

def call_vision(
    client: Anthropic,
    image_base64: str,
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 8192,
) -> str:
    """Send image to vision model, get response."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )
    return response.content[0].text


def parse_json_response(response_text: str) -> dict[str, Any]:
    """Parse JSON from vision response."""
    text = response_text.strip()

    # Remove markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end])

    # Find JSON object
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx == -1 or end_idx == -1:
        return {"error": "No JSON found in response"}

    json_str = text[start_idx : end_idx + 1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}


def parse_table_grid(
    response_text: str,
    table_id: str,
    source: TableSource,
    extraction_time_ms: float,
) -> TableGrid:
    """Parse vision response into TableGrid."""
    data = parse_json_response(response_text)

    if "error" in data:
        return TableGrid(
            table_id=table_id,
            source=source,
            error=data["error"],
            raw_response=response_text,
            extraction_time_ms=extraction_time_ms,
            confidence=0.0,
        )

    # Parse cells
    cells: list[TableCell] = []
    raw_cells = data.get("cells", [])

    for raw_cell in raw_cells:
        try:
            cell = TableCell(
                row=raw_cell.get("row", 0),
                col=raw_cell.get("col", 0),
                text=raw_cell.get("text"),
                row_span=raw_cell.get("row_span", 1),
                col_span=raw_cell.get("col_span", 1),
                is_header=raw_cell.get("is_header", False),
            )
            cells.append(cell)
        except Exception as e:
            logger.warning(f"Failed to parse cell {raw_cell}: {e}")

    row_count = data.get("row_count", 0)
    col_count = data.get("col_count", 0)

    # Infer row/col count if not provided
    if row_count == 0 and cells:
        row_count = max(c.row for c in cells) + 1
    if col_count == 0 and cells:
        col_count = max(c.col for c in cells) + 1

    grid = TableGrid(
        table_id=table_id,
        source=source,
        cells=cells,
        row_count=row_count,
        col_count=col_count,
        header_rows=data.get("header_rows", 1),
        caption=data.get("caption"),
        footnotes=data.get("footnotes"),
        extraction_time_ms=extraction_time_ms,
        raw_response=None,  # Don't store unless error
    )

    # Compute confidence from structural coverage
    grid.confidence = grid.structural_coverage

    return grid


# ---------------------------------------------------------------------------
# Main Extractor
# ---------------------------------------------------------------------------

class TableExtractorV10:
    """
    ATHENA-compliant table extractor.

    Uses TableGrid schema for faithful extraction without dict-by-header issues.
    Supports pdfplumber + vision fallback for table detection.
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        resolution: int = 150,
        use_vision_fallback: bool = True,
    ):
        self.model = model
        self.resolution = resolution
        self.use_vision_fallback = use_vision_fallback
        self.logger = logging.getLogger(self.__class__.__name__)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable required")

        if Anthropic is None:
            raise ImportError("anthropic package required: pip install anthropic")

        self.client = Anthropic(api_key=api_key)
        self._api_calls = 0

    def extract_pdf(self, pdf_path: Path) -> list[TableGrid]:
        """Extract all tables from a PDF using TableGrid schema."""
        pdf_path = Path(pdf_path)
        self.logger.info(f"Extracting: {pdf_path.name}")

        tables: list[TableGrid] = []
        tables_from_pdfplumber = 0
        tables_from_vision = 0

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_tables = page.find_tables()

                if page_tables:
                    tables_from_pdfplumber += len(page_tables)

                    for t_idx, table in enumerate(page_tables):
                        grid = self._extract_table(
                            page=page,
                            bbox=BBox.from_tuple(table.bbox),
                            pdf_path=pdf_path,
                            page_num=page_num,
                            table_idx=t_idx,
                        )
                        tables.append(grid)

                elif self.use_vision_fallback:
                    # Vision fallback for pages with no detected tables
                    vision_bboxes = self._detect_tables_vision(page)
                    tables_from_vision += len(vision_bboxes)

                    for t_idx, vbox in enumerate(vision_bboxes):
                        grid = self._extract_table(
                            page=page,
                            bbox=vbox,
                            pdf_path=pdf_path,
                            page_num=page_num,
                            table_idx=t_idx,
                        )
                        tables.append(grid)

        success = sum(1 for t in tables if not t.error)
        total_rows = sum(t.row_count for t in tables)
        self.logger.info(
            f"  -> {len(tables)} tables ({success} success), "
            f"{total_rows} rows, {self._api_calls} API calls "
            f"[pdfplumber: {tables_from_pdfplumber}, vision: {tables_from_vision}]"
        )

        return tables

    def _extract_table(
        self,
        page: pdfplumber.page.Page,
        bbox: BBox,
        pdf_path: Path,
        page_num: int,
        table_idx: int,
    ) -> TableGrid:
        """Extract a single table to TableGrid."""
        table_id = f"{pdf_path.stem}_p{page_num}_t{table_idx}"

        source = TableSource(
            document_path=str(pdf_path),
            document_name=pdf_path.name,
            page_number=page_num,
            table_index=table_idx,
            bbox=bbox,
            page_width=page.width,
            page_height=page.height,
        )

        self.logger.debug(f"  Processing {table_id}")

        # Render
        try:
            img_bytes = render_table_image(page, bbox, self.resolution)
            img_b64 = image_to_base64(img_bytes)
            source.image_size_kb = len(img_bytes) / 1024
        except Exception as e:
            self.logger.warning(f"  Failed to render {table_id}: {e}")
            return TableGrid(
                table_id=table_id,
                source=source,
                error=f"Render failed: {e}",
                confidence=0.0,
            )

        # Extract via vision
        extract_start = datetime.now()
        try:
            response = call_vision(
                self.client, img_b64, TABLE_EXTRACTION_PROMPT, self.model
            )
            self._api_calls += 1
            extract_time = (datetime.now() - extract_start).total_seconds() * 1000

            grid = parse_table_grid(response, table_id, source, extract_time)

        except Exception as e:
            self.logger.error(f"  Extraction failed {table_id}: {e}")
            extract_time = (datetime.now() - extract_start).total_seconds() * 1000
            grid = TableGrid(
                table_id=table_id,
                source=source,
                error=str(e),
                extraction_time_ms=extract_time,
                confidence=0.0,
            )

        self.logger.debug(
            f"    {grid.col_count} cols, {grid.row_count} rows, "
            f"conf={grid.confidence:.2f} ({grid.extraction_time_ms:.0f}ms)"
        )

        return grid

    def _detect_tables_vision(self, page: pdfplumber.page.Page) -> list[BBox]:
        """Use vision to detect table bboxes when pdfplumber fails."""
        try:
            img_bytes = render_full_page(page, self.resolution)
            img_b64 = image_to_base64(img_bytes)

            response = call_vision(
                self.client, img_b64, TABLE_DETECTION_PROMPT, self.model
            )
            self._api_calls += 1

            data = parse_json_response(response)
            raw_tables = data.get("tables", [])

            bboxes = []
            for t in raw_tables:
                raw_bbox = t.get("bbox", [])
                if len(raw_bbox) == 4:
                    # Vision returns pixels with top-left origin
                    bbox = BBox(
                        x0=raw_bbox[0],
                        y0=raw_bbox[1],
                        x1=raw_bbox[2],
                        y1=raw_bbox[3],
                        coord_space=CoordSpace.PAGE_PIXELS,
                        origin=Origin.TOP_LEFT,
                        dpi=self.resolution,
                    )
                    bboxes.append(bbox)

            return bboxes

        except Exception as e:
            self.logger.warning(f"Vision table detection failed: {e}")
            return []

    def extract_directory(
        self,
        input_dir: Path,
        output_path: Optional[Path] = None,
    ) -> ExtractionResult:
        """Extract all PDFs in a directory."""
        input_dir = Path(input_dir)
        start_time = datetime.now()
        self._api_calls = 0

        all_tables: list[TableGrid] = []
        failed_docs: list[str] = []
        pages_processed = 0

        pdf_files = sorted(input_dir.glob("*.pdf"))
        self.logger.info(f"Processing {len(pdf_files)} PDFs from {input_dir}")

        for pdf_file in pdf_files:
            try:
                with pdfplumber.open(pdf_file) as pdf:
                    pages_processed += len(pdf.pages)
                tables = self.extract_pdf(pdf_file)
                all_tables.extend(tables)
            except Exception as e:
                self.logger.error(f"Failed {pdf_file.name}: {e}")
                failed_docs.append(pdf_file.name)

        total_time = (datetime.now() - start_time).total_seconds()

        # Count by detection method
        pdfplumber_count = sum(
            1 for t in all_tables
            if t.source.bbox.coord_space == CoordSpace.PDF_POINTS
        )
        vision_count = sum(
            1 for t in all_tables
            if t.source.bbox.coord_space == CoordSpace.PAGE_PIXELS
        )

        result = ExtractionResult(
            extraction_timestamp=datetime.now().isoformat(),
            source=str(input_dir),
            documents_processed=len(pdf_files),
            pages_processed=pages_processed,
            tables_found_pdfplumber=pdfplumber_count,
            tables_found_vision=vision_count,
            tables_extracted=sum(1 for t in all_tables if not t.error),
            tables_failed=sum(1 for t in all_tables if t.error),
            total_rows=sum(t.row_count for t in all_tables),
            api_calls=self._api_calls,
            total_time_seconds=total_time,
            tables=all_tables,
            failed_documents=failed_docs,
        )

        if output_path:
            self._save_output(result, output_path)

        return result

    def extract_single(
        self,
        pdf_path: Path,
        output_path: Optional[Path] = None,
    ) -> ExtractionResult:
        """Extract tables from a single PDF."""
        pdf_path = Path(pdf_path)
        start_time = datetime.now()
        self._api_calls = 0
        pages_processed = 0

        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_processed = len(pdf.pages)
            tables = self.extract_pdf(pdf_path)
            failed_docs = []
        except Exception as e:
            self.logger.error(f"Failed {pdf_path.name}: {e}")
            tables = []
            failed_docs = [pdf_path.name]

        total_time = (datetime.now() - start_time).total_seconds()

        pdfplumber_count = sum(
            1 for t in tables
            if t.source.bbox.coord_space == CoordSpace.PDF_POINTS
        )
        vision_count = sum(
            1 for t in tables
            if t.source.bbox.coord_space == CoordSpace.PAGE_PIXELS
        )

        result = ExtractionResult(
            extraction_timestamp=datetime.now().isoformat(),
            source=str(pdf_path),
            documents_processed=1,
            pages_processed=pages_processed,
            tables_found_pdfplumber=pdfplumber_count,
            tables_found_vision=vision_count,
            tables_extracted=sum(1 for t in tables if not t.error),
            tables_failed=sum(1 for t in tables if t.error),
            total_rows=sum(t.row_count for t in tables),
            api_calls=self._api_calls,
            total_time_seconds=total_time,
            tables=tables,
            failed_documents=failed_docs,
        )

        if output_path:
            self._save_output(result, output_path)

        return result

    def _save_output(self, result: ExtractionResult, output_path: Path) -> None:
        """Save extraction results to JSON."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(result.model_dump(), f, indent=2, default=str)

        self.logger.info(f"Saved to {output_path}")


# ---------------------------------------------------------------------------
# Convenience Function
# ---------------------------------------------------------------------------

def extract_tables(
    input_path: Path,
    output_path: Optional[Path] = None,
    use_vision_fallback: bool = True,
) -> ExtractionResult:
    """Extract tables from PDF or directory using TableGrid schema."""
    extractor = TableExtractorV10(use_vision_fallback=use_vision_fallback)
    input_path = Path(input_path)

    if input_path.is_dir():
        return extractor.extract_directory(input_path, output_path)
    else:
        return extractor.extract_single(input_path, output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Table Extractor V10 - ATHENA-compliant TableGrid extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bok_extractor_v10.py document.pdf --output tables.json
  python bok_extractor_v10.py ./docs/ --output all_tables.json
  python bok_extractor_v10.py document.pdf --no-vision-fallback

Key improvements over V9:
  - TableGrid with cells[(row, col, text)] instead of dict-by-header
  - BBox model with explicit coord_space, origin, dpi
  - Structural coverage-based confidence
  - Vision fallback when pdfplumber finds 0 tables
  - Full provenance tracking per cell
        """,
    )
    parser.add_argument("input", type=Path, help="PDF file or directory")
    parser.add_argument("--output", "-o", type=Path, help="Output JSON path")
    parser.add_argument("--no-vision-fallback", action="store_true",
                        help="Disable vision fallback for table detection")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    result = extract_tables(
        args.input,
        args.output,
        use_vision_fallback=not args.no_vision_fallback,
    )

    # Print summary
    print(f"\n{'=' * 70}")
    print("EXTRACTION SUMMARY (V10 - TableGrid)")
    print(f"{'=' * 70}")
    print(f"Documents processed:     {result.documents_processed}")
    print(f"Pages processed:         {result.pages_processed}")
    print(f"Tables (pdfplumber):     {result.tables_found_pdfplumber}")
    print(f"Tables (vision):         {result.tables_found_vision}")
    print(f"Tables extracted:        {result.tables_extracted}")
    print(f"Tables failed:           {result.tables_failed}")
    print(f"Total rows:              {result.total_rows}")
    print(f"API calls:               {result.api_calls}")
    print(f"Time:                    {result.total_time_seconds:.1f}s")

    if result.tables:
        print(f"\n{'=' * 70}")
        print("SAMPLE TABLES")
        print(f"{'=' * 70}")

        for t in result.tables[:5]:
            print(f"\n{t.table_id} (page {t.source.page_number})")
            print(f"  Grid: {t.row_count} rows × {t.col_count} cols")
            print(f"  Headers: {t.get_column_headers()[:5]}{'...' if t.col_count > 5 else ''}")
            print(f"  Confidence: {t.confidence:.2f}")
            print(f"  Cells: {len(t.cells)}")
            if t.error:
                print(f"  ERROR: {t.error}")

    if result.failed_documents:
        print(f"\nFailed documents: {result.failed_documents}")
