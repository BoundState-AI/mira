#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Core Models for Table Extraction.

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

__safety_critical__ = True

from athena.core.bbox import BBox, CoordSpace, Origin
from athena.core.models import TableCell, TableGrid, TableSource, ExtractionResult

__all__ = [
    "BBox",
    "CoordSpace",
    "Origin",
    "TableCell",
    "TableGrid",
    "TableSource",
    "ExtractionResult",
]
