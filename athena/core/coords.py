#!/usr/bin/env python3
"""
Module: Coords
Purpose: Coordinate Transformation Utilities.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-033
Safety Critical: True
"""

from __future__ import annotations

from athena.core.bbox import BBox, CoordSpace, Origin

__all__ = [
    "pdf_points_to_pixels",
    "pixels_to_pdf_points",
    "create_pdf_bbox",
    "create_pixel_bbox",
]
__safety_critical__ = True


def pdf_points_to_pixels(
    bbox: BBox,
    page_height_points: float,
    dpi: int = 150,
) -> BBox:
    """
    Convert BBox from PDF points to page pixels.

    Args:
        bbox: Source bounding box (any coordinate system)
        page_height_points: PDF page height in points
        dpi: Target resolution

    Returns:
        BBox in page pixels with top-left origin
    """
    return bbox.to_page_pixels(page_height_points, dpi)


def pixels_to_pdf_points(
    bbox: BBox,
    page_height_points: float,
) -> BBox:
    """
    Convert BBox from page pixels to PDF points.

    Args:
        bbox: Source bounding box in page pixels
        page_height_points: PDF page height in points

    Returns:
        BBox in PDF points with bottom-left origin
    """
    return bbox.to_pdf_points(page_height_points)


def create_pdf_bbox(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> BBox:
    """
    Create a BBox in PDF points with bottom-left origin.

    This is the standard format for pdfplumber bounding boxes.
    """
    return BBox(
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        coord_space=CoordSpace.PDF_POINTS,
        origin=Origin.BOTTOM_LEFT,
    )


def create_pixel_bbox(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    dpi: int = 150,
) -> BBox:
    """
    Create a BBox in page pixels with top-left origin.

    This is the standard format for rendered images.
    """
    return BBox(
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        coord_space=CoordSpace.PAGE_PIXELS,
        origin=Origin.TOP_LEFT,
        dpi=dpi,
    )


def pdfplumber_bbox_to_model(
    bbox_tuple: tuple[float, float, float, float],
) -> BBox:
    """
    Convert pdfplumber bbox tuple to BBox model.

    pdfplumber returns (x0, top, x1, bottom) in PDF points,
    but uses top-left origin (y increases downward).
    """
    x0, top, x1, bottom = bbox_tuple
    return BBox(
        x0=x0,
        y0=top,
        x1=x1,
        y1=bottom,
        coord_space=CoordSpace.PDF_POINTS,
        origin=Origin.TOP_LEFT,  # pdfplumber uses top-left
    )
