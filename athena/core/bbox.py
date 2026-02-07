#!/usr/bin/env python3
"""
Module: Bbox
Purpose: BBox Model with Explicit Coordinate System.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-033 (traceability)
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, model_validator

__all__ = ["CoordSpace", "Origin", "BBox"]
__safety_critical__ = True


class CoordSpace(str, Enum):
    """Coordinate space for bounding boxes."""
    PDF_POINTS = "pdf_points"      # 72 points per inch, standard PDF
    PAGE_PIXELS = "page_pixels"    # Rendered image pixels


class Origin(str, Enum):
    """Origin point for coordinate system."""
    BOTTOM_LEFT = "bottom_left"    # PDF standard (y increases upward)
    TOP_LEFT = "top_left"          # Image standard (y increases downward)


class BBox(BaseModel):
    """
    Bounding box with explicit coordinate system.

    NEVER pass raw tuples. Always use this model.

    Compliance: SWE-033 (traceability)
    """
    model_config = {"extra": "forbid", "frozen": True}

    x0: float
    y0: float
    x1: float
    y1: float

    coord_space: CoordSpace
    origin: Origin
    dpi: Optional[int] = None  # Required if coord_space == PAGE_PIXELS

    @model_validator(mode="after")
    def validate_dpi(self) -> "BBox":
        if self.coord_space == CoordSpace.PAGE_PIXELS and self.dpi is None:
            raise ValueError("dpi required for PAGE_PIXELS coordinate space")
        return self

    @property
    def width(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)

    @property
    def as_tuple(self) -> tuple[float, float, float, float]:
        """For APIs that need raw tuples."""
        return (self.x0, self.y0, self.x1, self.y1)

    def to_pdf_points(self, page_height: float) -> "BBox":
        """Convert to PDF points with bottom-left origin."""
        if self.coord_space == CoordSpace.PDF_POINTS:
            if self.origin == Origin.BOTTOM_LEFT:
                return self
            # PDF points but top-left origin: flip y
            return BBox(
                x0=self.x0,
                y0=page_height - self.y1,
                x1=self.x1,
                y1=page_height - self.y0,
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
            )

        # Page pixels to PDF points
        if self.dpi is None:
            raise ValueError("Cannot convert: dpi not set")

        scale = 72.0 / self.dpi  # PDF points per pixel

        if self.origin == Origin.TOP_LEFT:
            # Flip y and scale
            return BBox(
                x0=self.x0 * scale,
                y0=page_height - (self.y1 * scale),
                x1=self.x1 * scale,
                y1=page_height - (self.y0 * scale),
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
            )
        else:
            # Just scale
            return BBox(
                x0=self.x0 * scale,
                y0=self.y0 * scale,
                x1=self.x1 * scale,
                y1=self.y1 * scale,
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
            )

    def to_page_pixels(self, page_height_points: float, dpi: int) -> "BBox":
        """Convert to page pixels with top-left origin."""
        if self.coord_space == CoordSpace.PAGE_PIXELS and self.origin == Origin.TOP_LEFT:
            if self.dpi == dpi:
                return self
            # Rescale
            scale = dpi / self.dpi
            return BBox(
                x0=self.x0 * scale,
                y0=self.y0 * scale,
                x1=self.x1 * scale,
                y1=self.y1 * scale,
                coord_space=CoordSpace.PAGE_PIXELS,
                origin=Origin.TOP_LEFT,
                dpi=dpi,
            )

        # Convert from PDF points
        pdf_bbox = self.to_pdf_points(page_height_points)
        scale = dpi / 72.0  # Pixels per PDF point
        page_height_pixels = page_height_points * scale

        return BBox(
            x0=pdf_bbox.x0 * scale,
            y0=page_height_pixels - (pdf_bbox.y1 * scale),  # Flip y
            x1=pdf_bbox.x1 * scale,
            y1=page_height_pixels - (pdf_bbox.y0 * scale),
            coord_space=CoordSpace.PAGE_PIXELS,
            origin=Origin.TOP_LEFT,
            dpi=dpi,
        )
