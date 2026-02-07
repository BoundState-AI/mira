#!/usr/bin/env python3
"""
Module: Detector
Purpose: ATHENA Table Detector.

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
import io
import json
import logging
from dataclasses import dataclass
from typing import Optional

import pdfplumber
from pdfplumber.page import Page

from athena.core.bbox import BBox, CoordSpace, Origin
from athena.extraction.prompts import TABLE_DETECTION_PROMPT

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

__all__ = ["TableDetector", "DetectedTable"]
__safety_critical__ = True

logger = logging.getLogger(__name__)


@dataclass
class DetectedTable:
    """A detected table region."""
    bbox: BBox
    page_number: int
    table_index: int
    detection_method: str  # "pdfplumber" or "vision"
    description: Optional[str] = None


class TableDetector:
    """
    Detects tables in PDF pages.

    Uses pdfplumber first (free, fast), falls back to vision
    when pdfplumber finds 0 tables on a page.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",  # Sonnet for borderless detection
        vision_fallback: bool = True,
        render_dpi: int = 150,
    ):
        self.model = model
        self.vision_fallback = vision_fallback
        self.render_dpi = render_dpi
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

    def detect_tables(self, page: Page, page_number: int) -> list[DetectedTable]:
        """
        Detect all tables on a page.

        Args:
            page: pdfplumber Page object
            page_number: 1-indexed page number

        Returns:
            List of DetectedTable objects
        """
        tables: list[DetectedTable] = []

        # Try pdfplumber first
        pdfplumber_tables = page.find_tables()

        if pdfplumber_tables:
            for idx, table in enumerate(pdfplumber_tables):
                bbox = BBox(
                    x0=table.bbox[0],
                    y0=table.bbox[1],
                    x1=table.bbox[2],
                    y1=table.bbox[3],
                    coord_space=CoordSpace.PDF_POINTS,
                    origin=Origin.TOP_LEFT,  # pdfplumber uses top-left
                )
                tables.append(DetectedTable(
                    bbox=bbox,
                    page_number=page_number,
                    table_index=idx,
                    detection_method="pdfplumber",
                ))

            self.logger.debug(
                f"Page {page_number}: pdfplumber found {len(tables)} tables"
            )
            return tables

        # Vision fallback if enabled and pdfplumber found nothing
        if self.vision_fallback:
            self.logger.debug(
                f"Page {page_number}: pdfplumber found 0 tables, trying vision"
            )
            vision_tables = self._detect_via_vision(page, page_number)
            tables.extend(vision_tables)

        return tables

    def _detect_via_vision(self, page: Page, page_number: int) -> list[DetectedTable]:
        """Use vision API to detect tables."""
        # Render page
        img = page.to_image(resolution=self.render_dpi)
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_b64 = base64.standard_b64encode(img_bytes.getvalue()).decode("utf-8")

        # Call vision API
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
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
                                "text": TABLE_DETECTION_PROMPT,
                            },
                        ],
                    }
                ],
            )
            response_text = response.content[0].text
        except Exception as e:
            self.logger.error(f"Vision detection failed: {e}")
            return []

        # Parse response
        tables = self._parse_detection_response(response_text, page_number, page.height)
        self.logger.debug(f"Page {page_number}: vision found {len(tables)} tables")
        return tables

    def _parse_detection_response(
        self,
        response_text: str,
        page_number: int,
        page_height: float,
    ) -> list[DetectedTable]:
        """Parse vision detection response into DetectedTable objects."""
        tables: list[DetectedTable] = []

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
            return tables

        try:
            data = json.loads(text[start_idx:end_idx + 1])
        except json.JSONDecodeError:
            return tables

        # Parse tables
        for idx, table_data in enumerate(data.get("tables", [])):
            bbox_list = table_data.get("bbox", [])
            if len(bbox_list) != 4:
                continue

            bbox = BBox(
                x0=bbox_list[0],
                y0=bbox_list[1],
                x1=bbox_list[2],
                y1=bbox_list[3],
                coord_space=CoordSpace.PAGE_PIXELS,
                origin=Origin.TOP_LEFT,
                dpi=self.render_dpi,
            )

            tables.append(DetectedTable(
                bbox=bbox,
                page_number=page_number,
                table_index=idx,
                detection_method="vision",
                description=table_data.get("description"),
            ))

        return tables
