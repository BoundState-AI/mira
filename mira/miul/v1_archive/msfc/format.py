#!/usr/bin/env python3
"""
Module: Format
Purpose: msfc_format.py

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, ASME Y14.1, ASME Y14.100
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
import uuid

__all__ = [
    "MSFCDrawingSize",
    "MSFCFormatSpec",
    "MSFCTitleBlockFields",
    "detect_msfc_format",
    "MSFC_FORMAT_PATTERN",
]

logger = logging.getLogger(__name__)


class MSFCDrawingSize(str, Enum):
    """Drawing sheet sizes per ASME Y14.1."""

    A = "A"   # 8.5 x 11 inches
    B = "B"   # 11 x 17 inches
    C = "C"   # 17 x 22 inches
    D = "D"   # 22 x 34 inches
    E = "E"   # 34 x 44 inches
    F = "F"   # 28 x 40 inches
    J = "J"   # 34 x 55 inches (extended)
    K = "K"   # 40 x 55 inches


# Pattern to detect MSFC format string in drawing
# Examples: MSFC_DWG_D_FORMAT_REV(B), MSFC_DWG_J_FORMAT_REV(B)
MSFC_FORMAT_PATTERN = re.compile(
    r"MSFC_DWG_([A-K])_FORMAT_REV\(([A-Z])\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MSFCTitleBlockFields:
    """Known field locations in MSFC title blocks.

    These are approximate zones for vision-based extraction.
    Coordinates are relative percentages of sheet dimensions.
    """

    # Title block is always lower-right quadrant
    title_block_x_start: float = 0.65  # 65% from left
    title_block_y_start: float = 0.75  # 75% from top

    # Individual field zones within title block (relative to title block)
    drawing_number_zone: tuple[float, float, float, float] = (0.5, 0.0, 1.0, 0.15)
    revision_zone: tuple[float, float, float, float] = (0.9, 0.0, 1.0, 0.1)
    title_zone: tuple[float, float, float, float] = (0.0, 0.15, 0.5, 0.35)
    material_zone: tuple[float, float, float, float] = (0.0, 0.35, 0.5, 0.50)
    weight_zone: tuple[float, float, float, float] = (0.7, 0.85, 0.85, 0.95)
    sheet_zone: tuple[float, float, float, float] = (0.85, 0.85, 1.0, 0.95)
    source: str = ""  # NASA SWE-013 traceability



class MSFCFormatSpec(BaseModel):
    """Specification for a detected MSFC drawing format."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    size: MSFCDrawingSize = Field(..., description="Sheet size code")
    format_revision: str = Field(..., description="Format revision letter")
    format_date: str | None = Field(None, description="Format date if detected")

    # Sheet dimensions in inches
    width_inches: float = Field(...)
    height_inches: float = Field(...)

    # Detected from drawing
    is_drawing_tree: bool = Field(False)
    is_multi_sheet: bool = Field(False)
    sheet_number: int = Field(1)
    total_sheets: int = Field(1)

    @classmethod
    def from_size(cls, size: MSFCDrawingSize, format_rev: str = "B") -> MSFCFormatSpec:
        """Create spec from size code."""
        dimensions = {
            MSFCDrawingSize.A: (11.0, 8.5),
            MSFCDrawingSize.B: (17.0, 11.0),
            MSFCDrawingSize.C: (22.0, 17.0),
            MSFCDrawingSize.D: (34.0, 22.0),
            MSFCDrawingSize.E: (44.0, 34.0),
            MSFCDrawingSize.F: (40.0, 28.0),
            MSFCDrawingSize.J: (55.0, 34.0),
            MSFCDrawingSize.K: (55.0, 40.0),
        }
        w, h = dimensions.get(size, (34.0, 22.0))

        return cls(
            size=size,
            format_revision=format_rev,
            width_inches=w,
            height_inches=h,
        )


def detect_msfc_format(text: str) -> MSFCFormatSpec | None:
    """Detect MSFC format from drawing text/OCR.

    Args:
        text: Text extracted from drawing (OCR or PDF text).

    Returns:
        Detected format spec or None if not MSFC format.
    """
    match = MSFC_FORMAT_PATTERN.search(text)
    if not match:
        logger.debug("No MSFC format pattern found in text")
        return None

    size_code = match.group(1).upper()
    format_rev = match.group(2).upper()

    try:
        size = MSFCDrawingSize(size_code)
    except ValueError:
        logger.warning(f"Unknown MSFC size code: {size_code}")
        return None

    spec = MSFCFormatSpec.from_size(size, format_rev)

    # Detect if this is a Drawing Tree
    if "-DT" in text.upper() or "DRAWING TREE" in text.upper():
        spec.is_drawing_tree = True

    # Detect sheet info (e.g., "SHEET 2 OF 4")
    sheet_match = re.search(r"SHEET\s+(\d+)\s+OF\s+(\d+)", text, re.IGNORECASE)
    if sheet_match:
        spec.sheet_number = int(sheet_match.group(1))
        spec.total_sheets = int(sheet_match.group(2))
        spec.is_multi_sheet = spec.total_sheets > 1

    # Detect format date (e.g., "(MARCH, 2019)")
    date_match = re.search(r"\(([A-Z]+,?\s*\d{4})\)", text, re.IGNORECASE)
    if date_match:
        spec.format_date = date_match.group(1)

    logger.info(f"Detected MSFC format: Size {size_code}, Rev {format_rev}")
    return spec
