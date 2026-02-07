#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Core Table Models.

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

# Import in dependency order
from athena.core.bbox import BBox
from athena.core.models.cell import TableCell
from athena.core.models.source import TableSource
from athena.core.models.grid import TableGrid
from athena.core.models.result import ExtractionResult

# Rebuild models to resolve forward references
TableCell.model_rebuild()
TableSource.model_rebuild()
TableGrid.model_rebuild()
ExtractionResult.model_rebuild()

__all__ = [
    "BBox",
    "TableCell",
    "TableGrid",
    "TableSource",
    "ExtractionResult",
]
