#!/usr/bin/env python3
"""
Module: Transcriber
Purpose: ATHENA Table Transcriber.

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

import base64
import hashlib
import io
import json
import logging
from datetime import datetime
from typing import Optional

import pdfplumber
from pdfplumber.page import Page

from athena.core.bbox import BBox, CoordSpace
from athena.core.models import TableCell, TableGrid, TableSource
from athena.extraction.prompts import TABLE_EXTRACTION_PROMPT
from athena.extraction.detector import DetectedTable

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

__all__ = ["TableTranscriber"]
__safety_critical__ = True

logger = logging.getLogger(__name__)


class TableTranscriber:
    """
    Transcribes detected table regions into TableGrid objects.

    Uses vision API to read table content and structure.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",  # Sonnet for borderless accuracy
        render_dpi: int = 150,
        padding: int = 15,
    ):
        self.model = model
        self.render_dpi = render_dpi
        self.padding = padding
        self.logger = logging.getLogger(self.__class__.__name__)

        self._client: Optional[Anthropic] = None

    @property
    def client(self) -> Anthropic:
        """Lazy-init Anthropic client."""
        if self._client is None:
            if Anthropic is None:
                raise ImportError("anthropic package required: pip install anthropic")
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable required")
            self._client = Anthropic(api_key=api_key)
        return self._client

    def transcribe(
        self,
        page: Page,
        detected: DetectedTable,
        pdf_path: str,
    ) -> TableGrid:
        """
        Transcribe a detected table region into a TableGrid.

        Args:
            page: pdfplumber Page object
            detected: DetectedTable from detector
            pdf_path: Path to source PDF

        Returns:
            TableGrid with extracted content
        """
        start_time = datetime.now()

        # Generate table ID (use Path for cross-platform compatibility)
        from pathlib import Path
        pdf_stem = Path(pdf_path).stem
        table_id = f"{pdf_stem}_p{detected.page_number}_t{detected.table_index}"

        # Render table region (or full page for vision-detected tables)
        try:
            if detected.detection_method == "vision":
                # Vision bbox is unreliable for borderless - use full page
                img_bytes = self._render_full_page(page)
                self.logger.debug(f"{table_id}: using full page (vision detection)")
            else:
                img_bytes = self._render_region(page, detected.bbox)
            img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
            img_size_kb = len(img_bytes) / 1024
            img_hash = hashlib.sha256(img_bytes).hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to render {table_id}: {e}")
            return self._create_error_grid(
                table_id, pdf_path, page, detected, str(e)
            )

        # Call vision API
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16384,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": img_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": TABLE_EXTRACTION_PROMPT,
                            },
                        ],
                    }
                ],
            )
            response_text = response.content[0].text
        except Exception as e:
            self.logger.error(f"Vision API failed for {table_id}: {e}")
            return self._create_error_grid(
                table_id, pdf_path, page, detected, str(e)
            )

        # Parse response into TableGrid
        extraction_time = (datetime.now() - start_time).total_seconds() * 1000

        grid = self._parse_response(
            response_text=response_text,
            table_id=table_id,
            pdf_path=pdf_path,
            page=page,
            detected=detected,
            img_hash=img_hash,
            extraction_time=extraction_time,
        )

        return grid

    def _render_full_page(self, page: Page) -> bytes:
        """Render full page to PNG bytes (for vision-detected tables)."""
        img = page.to_image(resolution=self.render_dpi)
        img_bytes = io.BytesIO()
        # Use img.original (raw PIL Image) not img.save() which may include overlays
        img.original.save(img_bytes, format="PNG")
        return img_bytes.getvalue()

    def _render_region(self, page: Page, bbox: BBox) -> bytes:
        """Render a table region to PNG bytes."""
        # Convert to PDF points if needed
        if bbox.coord_space != CoordSpace.PDF_POINTS:
            bbox = bbox.to_pdf_points(page.height)

        x0, y0, x1, y1 = bbox.x0, bbox.y0, bbox.x1, bbox.y1

        # Add padding
        pad_units = self.padding * 72 / self.render_dpi
        x0 = max(0, x0 - pad_units)
        y0 = max(0, y0 - pad_units)
        x1 = min(page.width, x1 + pad_units)
        y1 = min(page.height, y1 + pad_units)

        # Crop and render
        cropped = page.crop((x0, y0, x1, y1))
        img = cropped.to_image(resolution=self.render_dpi)

        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        return img_bytes.getvalue()

    def _parse_response(
        self,
        response_text: str,
        table_id: str,
        pdf_path: str,
        page: Page,
        detected: DetectedTable,
        img_hash: str,
        extraction_time: float,
    ) -> TableGrid:
        """Parse vision response into TableGrid."""
        # Clean response
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            start = 1
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end])

        # Find JSON
        start_idx = text.find("{")
        end_idx = text.rfind("}")

        if start_idx == -1 or end_idx == -1:
            return self._create_error_grid(
                table_id, pdf_path, page, detected,
                "No JSON found in response"
            )

        try:
            data = json.loads(text[start_idx:end_idx + 1])
        except json.JSONDecodeError as e:
            return self._create_error_grid(
                table_id, pdf_path, page, detected,
                f"JSON parse error: {e}"
            )

        # Extract cells
        cells: list[TableCell] = []
        for cell_data in data.get("cells", []):
            cell = TableCell(
                r=cell_data.get("r", cell_data.get("row", 0)),
                c=cell_data.get("c", cell_data.get("col", 0)),
                text=cell_data.get("text"),
                rowspan=cell_data.get("rowspan", cell_data.get("row_span", 1)),
                colspan=cell_data.get("colspan", cell_data.get("col_span", 1)),
            )
            cells.append(cell)

        # Create source
        source = TableSource(
            pdf_path=pdf_path,
            pdf_hash="",  # TODO: compute PDF hash
            page_number=detected.page_number,
            page_height_points=page.height,
            bbox=detected.bbox,
            table_index=detected.table_index,
            render_dpi=self.render_dpi,
            rendered_image_hash=img_hash,
            model_id=self.model,
        )

        # Create grid
        grid = TableGrid(
            table_id=table_id,
            cells=cells,
            row_count=data.get("row_count", max((c.r for c in cells), default=0) + 1),
            col_count=data.get("col_count", max((c.c for c in cells), default=0) + 1),
            header_row_count=data.get("header_rows", 1),
            context_text=data.get("context", data.get("caption")),
            footnotes_text=data.get("footnotes"),
            source=source,
            extraction_confidence=1.0,  # Will be computed by structural_coverage
            extraction_timestamp=datetime.now().isoformat(),
        )

        return grid

    def _create_error_grid(
        self,
        table_id: str,
        pdf_path: str,
        page: Page,
        detected: DetectedTable,
        error: str,
    ) -> TableGrid:
        """Create a TableGrid representing an extraction error."""
        source = TableSource(
            pdf_path=pdf_path,
            pdf_hash="",
            page_number=detected.page_number,
            page_height_points=page.height,
            bbox=detected.bbox,
            table_index=detected.table_index,
            render_dpi=self.render_dpi,
            model_id=self.model,
        )

        return TableGrid(
            table_id=table_id,
            cells=[],
            row_count=0,
            col_count=0,
            header_row_count=0,
            source=source,
            extraction_confidence=0.0,
            extraction_timestamp=datetime.now().isoformat(),
            error=error,
        )
