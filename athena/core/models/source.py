#!/usr/bin/env python3
"""
Module: Source
Purpose: TableSource Model.

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

from typing import Optional

from pydantic import BaseModel

from athena.core.bbox import BBox

__all__ = ["TableSource"]
__safety_critical__ = True


class TableSource(BaseModel):
    """Provenance for extracted table."""
    model_config = {"extra": "forbid"}

    # Document identity
    pdf_path: str
    pdf_hash: str                       # SHA256
    page_number: int                    # 1-indexed
    page_height_points: float           # For coordinate conversion

    # Table location - ALWAYS in PDF points, bottom-left origin
    bbox: BBox
    table_index: int                    # 0-indexed on page

    # Rendered image provenance
    render_dpi: int = 150
    render_bbox: Optional[BBox] = None  # In page pixels, top-left origin
    rendered_image_hash: Optional[str] = None  # SHA256 of PNG
    rendered_image_path: Optional[str] = None  # Debug mode only

    # Extraction metadata
    model_id: str = "claude-haiku-4-5-20251001"
    prompt_version: str = "1.5"
    raw_response_path: Optional[str] = None
